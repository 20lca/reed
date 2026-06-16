import os
from pathlib import Path

import bw2data as bd
import bw2io as bi
from bw2io.importers import ExcelImporter
from bw2io.importers.bonsai import BonsaiImporter
from bw2io.strategies.bonsai import mapb3

from reed.utils import CONFIG

# from ademe.bonsai_importer import BonsaiImporter
# from ademe.bonsai_strategies import mapb3


def define_b3_map() -> dict:

    biosphere_db = bd.Database(bd.config.biosphere)

    # mapping between elements in the intervention matrix and the biosphere database
    co_fossil = biosphere_db.get(name="Carbon monoxide, fossil", categories=("air",))
    co2_non_fossil = biosphere_db.get(
        name="Carbon dioxide, non-fossil", categories=("air",)
    )
    co2_fossil = biosphere_db.get(name="Carbon dioxide, fossil", categories=("air",))
    ch4_fossil = biosphere_db.get(name="Methane, fossil", categories=("air",))
    ch4_non_fossil = biosphere_db.get(name="Methane, non-fossil", categories=("air",))
    n2o = biosphere_db.get(name="Dinitrogen monoxide", categories=("air",))

    # mapping between the name in the B matrix and the code in biosphere db
    map_bonsai_b3 = {
        "Carbon_dioxide__fossil_Air": co2_fossil["code"],
        "Carbon_dioxide__biogenic_Air": co2_non_fossil["code"],
        "Methane__fossil_Air": ch4_fossil["code"],
        "Methane__biogenic_Air": ch4_non_fossil["code"],
        "Carbon_monoxide__fossil_Air": co2_non_fossil["code"],
        "Dinitrogen_monoxide_Air": n2o["code"],
    }

    return map_bonsai_b3


def import_bonsai(path_to_tidy_files: Path | None = None):
    """Creates a Brightway project called as defined in the config under utils.,
    and creates the following databases:
    - exiobase4 (technosphere activities/products)
    - biosphere3 (default elementary flows)
    - exiobase4 biosphere (elementary flows only present in exiobase)

    the path to tidy files can be provided as an argument, or otherwise it will
    assume the path specified in the config. If an environment variable with
    the name reed_bonsai_folder exists, it will override the value in the config
    file.
    """

    db_name = CONFIG.BONSAI_NAME

    # delete previous versions of the database
    try:
        del bd.databases[f"{db_name} biosphere"]
        del bd.databases[db_name]
        bd.Database(db_name).delete(warn=False)
        bd.Database(f"{db_name} biosphere").delete(warn=False)
    except KeyError:
        print("db not there")

    # import biosphere 3 if needed
    bi.remote.install_project(
        project_key="ecoinvent-3.10-biosphere",
        project_name=CONFIG.PROJECT_NAME,
        overwrite_existing=True,
    )

    bd.projects.set_current("reed")

    # select folder where the tidy version of exiobase is
    if path_to_tidy_files is None:
        bonsai_tidy_path = CONFIG.BONSAI_PATH
        # assert bonsai_tidy_path.exists(),bonsai_tidy_path
    else:
        bonsai_tidy_path = path_to_tidy_files

    # overwrite with environment variable if existing
    _bonsai_folder = os.environ.get("reed_bonsai_folder")

    if _bonsai_folder is not None:
        bonsai_tidy_path = Path(_bonsai_folder)

    assert bonsai_tidy_path.is_dir()

    # this is the old mapping that contains many flows that are not yet there
    # mapping_b3 = mapb3()

    mapping_b3 = define_b3_map()

    bonsai_v2_1_6 = BonsaiImporter(bonsai_tidy_path, db_name, b3mapping=mapping_b3)
    bonsai_v2_1_6.apply_strategies()
    bonsai_v2_1_6.write_database()


def import_reed_db(reed_path: Path | None = None):
    reed_root = reed_path or CONFIG.REED_PATH

    importer = ExcelImporter(
        reed_root / "Model" / "REED_model_20260506.xlsx",
    )
    importer.apply_strategies()
    importer.match_database(fields=["name", "unit", "location"])
    importer.match_database(
        db_name=CONFIG.BONSAI_NAME, fields=["name", "unit", "location", "activity type"]
    )
    importer.match_database(
        db_name=bd.config.biosphere, fields=["name", "categories", "unit"]
    )

    assert importer.all_linked

    importer.write_database()


if __name__ == "__main__":
    import_bonsai()
