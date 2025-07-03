# reed
work related to the REED Horizon Europe project


create conda virtual environment

```bash
 conda env create -f environment.yml
```

activate it and install reed package:

```bash
conda activate reed
pip install -e .
```

setup the project

```bash
cd scripts
python import_db.py
```
