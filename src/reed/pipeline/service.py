from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from reed.pipeline.models import NormalizedEventPayload
from reed.serializers.dpp import make_dpp_output
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
        score_a1, score_a2, score_a3, product_name, country = self._calculate_scores(
            payload, tool_energy
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
                raise PipelineError("validation_error", "sensor_data.records must not be empty")
            frame = pd.DataFrame([record.model_dump(exclude_none=True) for record in records])
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
    ) -> tuple[float, float, float, str, str]:
        try:
            import bw2calc as bc
            import bw2data as bd
        except ImportError as exc:
            raise PipelineError("dependency_missing", str(exc)) from exc

        from reed.swapping_data import (
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

        product_name = payload.product or f"{payload.company.upper()} total"
        product_activity = self._get_product_activity(reed, product_name, payload.country)
        country = payload.country or product_activity.get("location") or "GB"

        try:
            a3_activity = find_subactivity_by_name_fragment(product_activity, "A3")[0]
        except IndexError as exc:
            raise PipelineError("a3_not_found", f"A3 phase not found for {product_name}") from exc

        tools = tool_energy_by_company_and_event.index.get_level_values("reed tool").unique()
        found = {tool: find_activities_by_name(reed, tool, exact=False) for tool in tools}

        electricity = self._get_electricity_activity(bonsai, country)
        scenarios = build_scenarios_from_power_active(
            tool_energy_by_company_and_event, found, electricity
        )
        consumer_scenarios = build_consumer_input_scenarios_from_hours_for_activity(
            tool_energy_by_company_and_event,
            found,
            a3_activity,
        )

        frames = [frame for frame in (scenarios, consumer_scenarios) if not frame.empty]
        full_scenario = pd.concat(frames) if frames else None

        def lcia_score_for_named_input(
            name_fragment: str,
            scenario_df: pd.DataFrame | None = None,
        ) -> float:
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
                    fu, data_objs, _ = bd.prepare_lca_inputs(
                        {input_activity: input_amount},
                        method=self.settings.lcia_gwp100,
                    )
                    lca = bc.LCA(fu, method=self.settings.lcia_gwp100, data_objs=data_objs)
                    lca.lci()
                    lca.lcia()
                    total_score += lca.score
                else:
                    score, _ = lcia_for_activity_with_scenario(
                        activity=input_activity,
                        method=self.settings.lcia_gwp100,
                        scenario_df=scenario_df,
                        amount=input_amount,
                    )
                    total_score += score
            return total_score

        score_a1 = lcia_score_for_named_input("A1", full_scenario)
        score_a2 = lcia_score_for_named_input("A2", full_scenario)
        score_a3 = lcia_score_for_named_input("A3", full_scenario)
        return score_a1, score_a2, score_a3, product_name, country

    def _get_product_activity(self, reed_db, product_name: str, country: str | None):
        if country:
            try:
                return reed_db.get(name=product_name, location=country)
            except Exception:
                pass

        try:
            return reed_db.get(name=product_name)
        except Exception as exc:
            raise PipelineError("product_not_found", f"Product '{product_name}' not found") from exc

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
