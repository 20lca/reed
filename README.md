# reed
work related to the REED Horizon Europe project


create conda virtual environment named `reed`

```bash
conda env create -f environment.yml
```

activate it and install reed package:

```bash
conda activate reed
pip install -e .
```

setup the project. This installs a biosphere database and one functioning version of bonsai

```bash
cd scripts
python import_db.py
```

```python
from reed import utils
from bw2io.importers import ExcelImporter
config = utils.Config()
importer  = ExcelImporter(config.REED_PATH/'Model'/'reed_inventories.xlsx')
importer.match_database(fields=['name','unit','location'])
importer.match_database(db_name=bonsai.name,fields=['name','unit','location','activity type'])
importer.write_database()

```