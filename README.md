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

## Client API Usage

Set the base URL and archive path:

```powershell
$baseUrl = "http://127.0.0.1:8000"
$file = "C:\path\to\OF10005.tar.gz"
```

Submit a calculation request (`product` is required):

```powershell
curl.exe -X POST "$baseUrl/v1/calculations" `
  -F "archive=@$file;type=application/gzip" `
  -F "product=GOIMEK total" `
  -F "country=ES" `
  -F "calculation_kind=monitoring" `
  -F "finished=false"
```

Allowed products: `product` must be one of `WWR total`, `GOIMEK total`, or `KOMATSU total`. Any other value is rejected before calculation starts.

The API returns `202 Accepted` with a `job_id` and `result_id`.

Set `finished=false` (or `0`) for an in-progress production snapshot. Its result contains the current total climate impact and machining contributions. Set `finished=true` (or `1`) for the final upload to generate the full DPP result. `finished` defaults to `true` for backward compatibility.

Set `calculation_kind=simulation` to run the simulation workflow with the same upload/job/result/consume lifecycle. Simulation results are not DPP documents; they include product total, A1 raw materials, A2 transport, and A3 machining operation contributions. Each machining operation exposes its scenario-derived `amount` and climate-impact `score` in kg CO2-eq. `calculation_kind` defaults to `monitoring`.

Poll the job until `status` is `completed` or `failed`:

```powershell
curl.exe "$baseUrl/v1/calculations/<job_id>"
```

Fetch the completed result:

```powershell
curl.exe "$baseUrl/v1/results/<result_id>"
```

After the client has successfully stored or processed the result, consume it to delete the temporary result artifact:

```powershell
curl.exe -X POST "$baseUrl/v1/results/<result_id>/consume"
```

For deployed clients, replace `$baseUrl` with the production URL, for example `https://bonsai.uno/reed`. The maximum upload archive size is 500 MB. If exceeded, the API returns an error with `413 Request Entity Too Large`.

Conda is optional. `environment.yml` is kept for legacy notebook workflows and heavier geospatial/visualization dependencies, but it is not required for the REST service.
