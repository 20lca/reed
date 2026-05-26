import bw2data as bd
import pandas as pd

from reed.LCA_functions import lca_score

from .utils import CONFIG, Config


def import_bonsai(path_to_tidy_files):
    from .import_db import import_bonsai as import_bonsai_impl

    return import_bonsai_impl(path_to_tidy_files)


def import_reed_db():
    from .import_db import import_reed_db as import_reed_db_impl

    return import_reed_db_impl()


def required_brightway_databases(settings: Config = CONFIG) -> set[str]:
    """Return database names required before REED calculations can run."""
    return {
        "reed",
        settings.BONSAI_NAME,
        f"{settings.BONSAI_NAME} biosphere",
    }


def missing_brightway_databases(settings: Config = CONFIG) -> list[str]:
    """Return required Brightway databases missing from the configured project."""
    bd.projects.set_current(settings.PROJECT_NAME)
    existing = set(bd.databases)
    return sorted(required_brightway_databases(settings) - existing)


def ensure_brightway_databases(settings: Config = CONFIG) -> None:
    """Import Brightway databases once at startup if the project is incomplete."""
    missing = missing_brightway_databases(settings)
    if not missing:
        return

    bonsai_path = settings.BONSAI_PATH
    if not bonsai_path.exists():
        raise RuntimeError(
            "Brightway startup import required but BONSAI_PATH does not exist: "
            f"{bonsai_path}. Missing databases: {', '.join(missing)}"
        )

    try:
        import_bonsai(bonsai_path)
        import_reed_db()
    except Exception as exc:
        raise RuntimeError(
            "Brightway startup import failed. "
            f"Missing databases before import: {', '.join(missing)}. "
            f"BONSAI_PATH: {bonsai_path}. Error: {exc}"
        ) from exc

    still_missing = missing_brightway_databases(settings)
    if still_missing:
        raise RuntimeError(
            "Brightway startup import completed but required databases are still "
            f"missing: {', '.join(still_missing)}"
        )


class BrightwayAPI:
    def __init__(self):
        bd.projects.set_current(CONFIG.PROJECT_NAME)
        self.PROJECT_NAME = CONFIG.PROJECT_NAME

    def import_databases(self):
        """Import BONSAI and the foreground machining database."""
        ensure_brightway_databases(CONFIG)

    def calc_komatsu(self) -> pd.DataFrame:
        reed = bd.Database("reed")
        assert len(reed) > 0, "reed database is empty"

        komatsu_processes = {
            "KOMATSU total": reed.get(name="KOMATSU total", location="GB", unit="unit"),
            "KOMATSU A1: raw materials": reed.get(
                name="KOMATSU A1: raw materials", location="GB", unit="unit"
            ),
            "KOMATSU A2: transport": reed.get(
                name="KOMATSU A2: transport", location="GB", unit="unit"
            ),
            "KOMATSU A3: machining": reed.get(
                name="KOMATSU A3: machining", location="GB", unit="unit"
            ),
        }

        return lca_score(komatsu_processes, CONFIG.lcia_gwp100)

    def calc_wwr(self) -> pd.DataFrame:
        reed = bd.Database("reed")
        assert len(reed) > 0, "reed database is empty"

        wwr_processes = {
            "WWR total": reed.get(name="WWR total", location="DE", unit="unit"),
            "WWR A1: material inputs": reed.get(
                name="WWR A1: material inputs", location="DE", unit="unit"
            ),
            "WWR A2: transport": reed.get(
                name="WWR A2: transport", location="DE", unit="unit"
            ),
            "WWR A3: machining": reed.get(
                name="WWR A3: machining", location="DE", unit="unit"
            ),
        }

        return lca_score(wwr_processes, CONFIG.lcia_gwp100)

    def calc_goimek(self) -> pd.DataFrame:
        reed = bd.Database("reed")
        assert len(reed) > 0, "reed database is empty"

        goimek_processes = {
            "GOIMEK total": reed.get(name="GOIMEK total", location="ES", unit="unit"),
            "GOIMEK A1: material input": reed.get(
                name="GOIMEK A1: material input", location="ES", unit="unit"
            ),
            "GOIMEK A2: transport": reed.get(
                name="GOIMEK A2: transport", location="ES", unit="unit"
            ),
            "GOIMEK A3: machining": reed.get(
                name="GOIMEK A3: machining", location="ES", unit="unit"
            ),
        }

        return lca_score(goimek_processes, CONFIG.lcia_gwp100)

    def simulate(self, simulation_data: dict) -> pd.DataFrame:
        raise NotImplementedError

    def evaluate(self, sensor_data: dict):
        raise NotImplementedError
