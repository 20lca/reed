# reed
work related to the REED Horizon Europe project

Go to the repository:

```powershell
cd C:\path\to\reed
```

Create and activate a Python virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the package in editable mode:

```powershell
python -m pip install -e .
```

Configure local paths with dotenv:

```powershell
copy .env.example .env
```

Then edit `.env` and set `REED_PATH` to the root folder that contains the REED `Model` and `data` folders:

```dotenv
REED_PATH=C:\path\to\EU_REED_1277
STORAGE_ROOT=storage
```

`BONSAI_PATH` is derived automatically as `REED_PATH/data/BONSAI_V2.1.6` unless you set `BONSAI_PATH` explicitly.
`STORAGE_ROOT` is where submitted payloads, job metadata, archives, and temporary results are stored.

Start the API:

```powershell
uvicorn reed.api.main:app --reload
```

On startup, the API checks the configured Brightway project and imports the required BONSAI and REED databases if they are missing.

Conda is optional. `environment.yml` is kept for legacy notebook workflows and heavier geospatial/visualization dependencies, but it is not required for the REST service.
