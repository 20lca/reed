from reed.utils import Config
from bw2io.importers import ExcelImporter
from reed.utils import Config
import bw2data as bd



def test_lcia_method():

    config = Config()

    assert isinstance(config.lcia_gwp100,tuple)

def test_database_is_all_linked():
    
    config = Config()
    bd.projects.set_current(config.PROJECT_NAME)

    bonsai = bd.Database('bonsai_231231')
    bonsai_bio = bd.Database('bonsai_231231 biosphere')
    ecoinvent = bd.Database('ecoinvent-3.10-biosphere')
    reed = bd.Database('reed')

    importer  = ExcelImporter(config.REED_PATH/'model'/'REED_model_20251023.xlsx',)
    importer.match_database(fields=['name','unit','location'])
    importer.match_database(db_name=bonsai.name,fields=['name','unit','location','activity type'])
    importer.match_database(db_name=bd.config.biosphere,fields=['name','categories','unit'])

    assert importer.all_linked