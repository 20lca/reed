import bw2data as bd
import pandas as pd

from reed.LCA_functions import lca_score

from .import_db import import_bonsai, import_reed_db
from .utils import CONFIG


class BrightwayAPI:
    def __init__(self):
        bd.projects.set_current(CONFIG.PROJECT_NAME)
        self.PROJECT_NAME = CONFIG.PROJECT_NAME

    def import_databases(self):
        """Import BONSAI and the foreground machining database."""
        import_bonsai(CONFIG.BONSAI_PATH)
        import_reed_db()

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
