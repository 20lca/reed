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
