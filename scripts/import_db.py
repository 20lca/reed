from pathlib import Path
import os

import bw2data as bd
import bw2io as bi

from bw2io.importers.bonsai import BonsaiImporter
from bw2io.strategies.bonsai import mapb3

from reed import utils
# from ademe.bonsai_importer import BonsaiImporter
# from ademe.bonsai_strategies import mapb3

def main(path_to_tidy_files:Path=None):
    """Creates a Brightway project called as defined in the config under utils., 
    and creates the following databases:
    - exiobase4 (technosphere activities/products)
    - biosphere3 (default elementary flows)
    - exiobase4 biosphere (elementary flows only present in exiobase)
    """
    config = utils.Config()

    # select folder where the tidy version of exiobase is
    if path_to_tidy_files is None:
        
        bonsai_tidy_path = config.BONSAI_PATH
        #assert exio_tidy_path.exists(),exio_tidy_path
    else:
        bonsai_tidy_path = path_to_tidy_files

    # overwrite with environment variable if existing
    _bonsai_folder = os.environ.get('reed_bonsai_folder')

    if _bonsai_folder is not None:
        
        exio_tidy_path = Path(_bonsai_folder)

    assert bonsai_tidy_path.is_dir()

    db_name = config.BONSAI_NAME
    
    bd.projects.set_current('reed')
    # delete previous versions of the database
    try:
        del bd.databases[f'{db_name} biosphere']
        del bd.databases[db_name]
        bd.Database(db_name).delete(warn=False)
        bd.Database(f'{db_name} biosphere').delete(warn=False)
    except KeyError:
        print('db not there')



    mapping_b3 = mapb3()

    bonsai_v2_1_3 = BonsaiImporter(bonsai_tidy_path,db_name,b3mapping=mapping_b3)
    bonsai_v2_1_3.apply_strategies()
    bonsai_v2_1_3.write_database()

if __name__ == '__main__':
    main()