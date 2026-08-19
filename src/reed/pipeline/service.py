from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from reed.pipeline.models import NormalizedEventPayload
from reed.serializers.dpp import make_dpp_output
from reed.serializers.monitoring import make_monitoring_output
from reed.serializers.simulation import make_simulation_output
from reed.utils import Config


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ReedCalculationPipeline:
    settings: Config

    def run(self, payload: NormalizedEventPayload) -> dict[str, object]:
        tool_energy = self._aggregate_sensor_data(payload)
        (
            score_a1,
            score_a2,
            score_a3,
            product_name,
            country,
            machining_contributions,
        ) = self._calculate_scores(payload, tool_energy)
        if payload.calculation_kind == "simulation":
            return make_simulation_output(
                product=product_name,
                score_a1=score_a1,
                score_a2=score_a2,
                score_a3=score_a3,
                machining_contributions=machining_contributions,
            )

        if not payload.finished:
            return make_monitoring_output(
                product=product_name,
                total_climate_impact=score_a1 + score_a2 + score_a3,
                machining_contributions=machining_contributions,
            )

        return make_dpp_output(
            company=payload.company,
            event_id=payload.event_id,
            product=product_name,
            country=country,
            publication_date=date.today(),
            score_a1=score_a1,
            score_a2=score_a2,
            score_a3=score_a3,
        )

    def _aggregate_sensor_data(self, payload: NormalizedEventPayload) -> pd.DataFrame:
        from reed.sensordata_analysis import (
            build_final_df,
            load_records_from_archive_path,
            load_tool_operation_keys,
            sum_by_reed_tool,
        )

        if payload.archive.storage_path:
            try:
                archive_records = load_records_from_archive_path(
                    payload.archive.storage_path,
                    archive_name=payload.archive.original_filename,
                )
            except ValueError as exc:
                raise PipelineError("validation_error", str(exc)) from exc
        else:
            records = payload.sensor_data.records
            if not records:
                raise PipelineError(
                    "validation_error", "sensor_data.records must not be empty"
                )
            frame = pd.DataFrame(
                [record.model_dump(exclude_none=True) for record in records]
            )
            archive_records = [
                {
                    "company": payload.company,
                    "event_id": payload.event_id,
                    "data": frame,
                }
            ]

        tool_path = Path(self.settings.TOOL_DESCRIPTIONS_PATH)
        workbook = tool_path / "tool_operation_combined.xlsx"
        if not workbook.exists():
            raise PipelineError(
                "mapping_not_found",
                f"tool mapping workbook not found at {workbook}",
            )

        event_records = {(payload.company, payload.event_id): archive_records}
        key_company_tools, key_reed_tools, _ = load_tool_operation_keys(tool_path)
        final_df, _ = build_final_df(event_records, key_company_tools, key_reed_tools)
        return sum_by_reed_tool(final_df)

    def _calculate_scores(
        self,
        payload: NormalizedEventPayload,
        tool_energy_by_company_and_event: pd.DataFrame,
    ) -> tuple[float, float, float, str, str, list[dict[str, object]]]:
        try:
            import bw2calc as bc
            import bw2data as bd
        except ImportError as exc:
            raise PipelineError("dependency_missing", str(exc)) from exc

        from reed.swapping_data import (
            _build_scenario_datapackage,
            build_consumer_input_scenarios_from_hours_for_activity,
            build_scenarios_from_power_active,
            find_activities_by_name,
            find_subactivity_by_name_fragment,
            lcia_for_activity_with_scenario,
        )

        bd.projects.set_current(self.settings.PROJECT_NAME)

        try:
            reed = bd.Database("reed")
        except Exception as exc:
            raise PipelineError("brightway_project_error", str(exc)) from exc

        try:
            bonsai = bd.Database(self.settings.BONSAI_NAME)
        except Exception as exc:
            raise PipelineError("bonsai_database_error", str(exc)) from exc

        product_name = payload.product.value
        product_activity = self._get_product_activity(
            reed, product_name, payload.country
        )
        country = payload.country or product_activity.get("location")

        try:
            a3_activity = find_subactivity_by_name_fragment(product_activity, "A3")[0]
        except IndexError as exc:
            raise PipelineError(
                "a3_not_found", f"A3 phase not found for {product_name}"
            ) from exc

        scenario_consumer = a3_activity
        if payload.calculation_kind == "simulation" or not payload.finished:
            from reed.LCA_functions import get_machining_activity

            try:
                scenario_consumer = get_machining_activity(product_activity)
            except ValueError as exc:
                raise PipelineError("machining_activity_not_found", str(exc)) from exc

        tools = tool_energy_by_company_and_event.index.get_level_values(
            "reed tool"
        ).unique()
        found = {
            tool: find_activities_by_name(reed, tool, exact=False) for tool in tools
        }

        electricity = self._get_electricity_activity(bonsai, country)
        scenarios = build_scenarios_from_power_active(
            tool_energy_by_company_and_event, found, electricity
        )
        consumer_scenarios = build_consumer_input_scenarios_from_hours_for_activity(
            tool_energy_by_company_and_event,
            found,
            scenario_consumer,
        )
        machining_contributions = self._machining_contributions(
            scenario_consumer,
            consumer_scenarios,
        )

        frames = [frame for frame in (scenarios, consumer_scenarios) if not frame.empty]
        full_scenario = pd.concat(frames) if frames else None

        # Build the scenario datapackage once; all three phases share the same overrides.
        # The sequential-mode cursor only advances on matrix build, so sharing is safe.
        scenario_dp = (
            _build_scenario_datapackage(full_scenario) if full_scenario is not None else None
        )

        def lcia_score_for_named_input(
            name_fragment: str,
            scenario_df: pd.DataFrame | None = None,
            *,
            dp=None,
            lca_obj=None,
        ) -> tuple[float, object]:
            """Score all technosphere inputs of product_activity matching name_fragment.

            Returns (total_score, lca_obj) so the caller can thread the LCA object
            through subsequent phases, reusing the already-factorised technosphere matrix.
            """
            matches = [
                exc
                for exc in product_activity.technosphere()
                if name_fragment.lower() in exc.input.get("name", "").lower()
            ]
            if not matches:
                raise PipelineError(
                    "phase_not_found",
                    f"No input containing '{name_fragment}' found in {product_name}",
                )

            total_score = 0.0
            for exc in matches:
                input_activity = exc.input
                input_amount = float(exc["amount"])
                if scenario_df is None:
                    # No scenario: always create a fresh LCA object (matrices differ per phase)
                    fu, data_objs, _ = bd.prepare_lca_inputs(
                        {input_activity: input_amount},
                        method=self.settings.lcia_gwp100,
                    )
                    lca_obj = bc.LCA(
                        fu, method=self.settings.lcia_gwp100, data_objs=data_objs
                    )
                    lca_obj.lci()
                    lca_obj.lcia()
                    total_score += lca_obj.score
                elif lca_obj is None:
                    # First scenario call: build the full LCA object with the shared dp
                    score, lca_obj = lcia_for_activity_with_scenario(
                        activity=input_activity,
                        method=self.settings.lcia_gwp100,
                        scenario_df=scenario_df,
                        amount=input_amount,
                        dp=dp,
                    )
                    total_score += score
                else:
                    # Subsequent scenario calls: reuse the factorised technosphere matrix.
                    # lca.lci(demand=...) skips load_lci_data() because technosphere_matrix
                    # already exists; only the demand vector and linear solve are repeated.
                    # bw2calc requires an integer node ID as the demand key (not an Activity
                    # object); see check_demand() in bw2calc/lca.py.
                    lca_obj.lci(demand={input_activity.id: input_amount})
                    lca_obj.lcia()
                    total_score += lca_obj.score

            return total_score, lca_obj

        score_a1, lca_obj = lcia_score_for_named_input(
            "A1", full_scenario, dp=scenario_dp
        )
        score_a2, lca_obj = lcia_score_for_named_input(
            "A2", full_scenario, dp=scenario_dp, lca_obj=lca_obj
        )
        score_a3, lca_obj = lcia_score_for_named_input(
            "A3", full_scenario, dp=scenario_dp, lca_obj=lca_obj
        )
        machining_contributions = self._score_machining_contributions(
            scenario_consumer,
            machining_contributions,
            lca_obj,
        )
        return (
            score_a1,
            score_a2,
            score_a3,
            product_name,
            country,
            machining_contributions,
        )

    def _machining_contributions(
        self,
        machining_activity,
        consumer_scenarios: pd.DataFrame,
    ) -> list[dict[str, object]]:
        scenario_values: dict[tuple[int, int], float] = {}
        if not consumer_scenarios.empty:
            scenario_column = next(
                column
                for column in consumer_scenarios.columns
                if column != "original"
            )
            scenario_values = {
                (int(product_id), int(activity_id)): float(value)
                for (product_id, activity_id), value in consumer_scenarios[
                    scenario_column
                ].items()
            }

        contributions = []
        for exchange in machining_activity.technosphere():
            amount = scenario_values.get(
                (exchange.input.id, machining_activity.id),
                float(exchange["amount"]),
            )
            contributions.append(
                {
                    "operation": exchange.input.get("name", ""),
                    "amount": amount,
                }
            )
        return contributions

    def _score_machining_contributions(
        self,
        machining_activity,
        contributions: list[dict[str, object]],
        lca_obj,
    ) -> list[dict[str, object]]:
        """Score each operation demand with the already-built scenario matrix."""
        scored = []
        exchanges = list(machining_activity.technosphere())
        for exchange, contribution in zip(exchanges, contributions, strict=True):
            amount = float(contribution["amount"])
            lca_obj.lci(demand={exchange.input.id: amount})
            lca_obj.lcia()
            scored.append({**contribution, "score": float(lca_obj.score)})
        return scored

    def _get_product_activity(self, reed_db, product_name: str, country: str | None):
        if country:
            try:
                return reed_db.get(name=product_name, location=country)
            except Exception:
                pass

        try:
            return reed_db.get(name=product_name)
        except Exception as exc:
            raise PipelineError(
                "product_not_found", f"Product '{product_name}' not found"
            ) from exc

    def _get_electricity_activity(self, bonsai_db, country: str):
        activity_name = "production of electricity (market for)"
        for location in (country, "GB"):
            try:
                return bonsai_db.get(name=activity_name, location=location, unit="TJ")
            except Exception:
                continue
        raise PipelineError(
            "electricity_not_found",
            f"Electricity market activity not found for {country} or GB",
        )
