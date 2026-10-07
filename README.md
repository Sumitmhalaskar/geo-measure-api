# Geo Measure API

A backend service built with **FastAPI** that accepts a geospatial file (a **KML** or a **zipped Shapefile**), extracts every feature, and returns measurements: **area** for polygons and **length** for lines. Measurements are always computed in a projected, metric coordinate system, never directly on latitude/longitude degrees.

## Features

- Upload a `.kml` or a `.zip` containing a Shapefile
- Extracts per-feature index, geometry type, geometry (GeoJSON), CRS and properties
- Polygon area (m²) and line length (m), calculated after reprojecting to a suitable UTM zone
- Graceful handling of unsupported, empty and invalid geometries (one bad feature never fails the whole file)
- Safe zip extraction (zip-slip and zip-bomb protection) and upload size limit
- Paginated results, interactive Swagger docs at `/docs`
- 21 automated tests, including a cross-check against an independent geodesic calculation

---

## Setup

### Requirements

- Python 3.10 or newer (developed and tested on Python 3.14)

### Run locally

```bash
git clone https://github.com/Sumitmhalaskar/geo-measure-api.git
cd geo-measure-api

# create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows (PowerShell)
# source venv/bin/activate     # macOS / Linux

# install dependencies
python -m pip install -r requirements.txt

# start the server
python -m uvicorn app.main:app --reload
```

The API is now available at `http://127.0.0.1:8000`, and the interactive docs at `http://127.0.0.1:8000/docs`.

On Windows PowerShell, if activation is blocked, run `Set-ExecutionPolicy -Scope Process Bypass` first.

### Run the tests

```bash
python -m pytest -v
```

### Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./geo.db` | SQLAlchemy database URL |

A sample file is included at `tests/data/survey.kml` (a polygon, a line and a point).

---

## API

Base path: `/api/files`. All responses are JSON.

### `POST /api/files/` – upload and process a file

Accepts `multipart/form-data` with a single `file` field (`.kml` or `.zip` containing a Shapefile).

```bash
curl -X POST http://127.0.0.1:8000/api/files/ \
  -F "file=@tests/data/survey.kml"
```

On Windows PowerShell use `curl.exe` instead of `curl`.

Response `201 Created`:

```json
{
  "id": "79877e0982904f4ea91eab993942c97e",
  "filename": "survey.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "crs_assumed": false,
  "status": "COMPLETED"
}
```

| Status | Meaning |
|---|---|
| `201` | File uploaded and processed |
| `400` | Unsupported file type (only `.kml` and `.zip`) |
| `413` | File larger than 50 MB |
| `422` | File could not be read (corrupt file, no `.shp` in the zip, missing CRS, unsafe zip). The body includes the `file_id` of the failed record |

### `GET /api/files/{id}/` – file information

```bash
curl http://127.0.0.1:8000/api/files/79877e0982904f4ea91eab993942c97e/
```

```json
{
  "id": "79877e0982904f4ea91eab993942c97e",
  "filename": "survey.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "crs_assumed": false,
  "status": "COMPLETED"
}
```

`status` is one of `PROCESSING`, `COMPLETED` or `FAILED`. When `FAILED`, an `error_message` field explains why. Unknown ids return `404`.

### `GET /api/files/{id}/measurements/` – measurements per feature

Query parameters: `limit` (1–1000, default 100) and `offset` (default 0).

```bash
curl "http://127.0.0.1:8000/api/files/79877e0982904f4ea91eab993942c97e/measurements/"
```

The `properties` objects below are shortened. Real KML files return every attribute the file contains.

```json
{
  "file_id": "79877e0982904f4ea91eab993942c97e",
  "total": 3,
  "limit": 100,
  "offset": 0,
  "measurements": [
    {
      "feature_index": 0,
      "geometry_type": "Polygon",
      "crs": "EPSG:4326",
      "properties": { "Name": "Plot A" },
      "measurement_status": "OK",
      "area_sq_m": 1164848.5734,
      "projected_crs": "EPSG:32643"
    },
    {
      "feature_index": 1,
      "geometry_type": "LineString",
      "crs": "EPSG:4326",
      "properties": { "Name": "Road 1" },
      "measurement_status": "OK",
      "length_m": 10526.2916,
      "projected_crs": "EPSG:32643"
    },
    {
      "feature_index": 2,
      "geometry_type": "Point",
      "crs": "EPSG:4326",
      "properties": { "Name": "Well" },
      "measurement_status": "NOT_REQUIRED",
      "message": "No measurement for points"
    }
  ]
}
```

`measurement_status` values:

| Value | Meaning |
|---|---|
| `OK` | Area or length was calculated |
| `NOT_REQUIRED` | Points need no measurement |
| `UNSUPPORTED` | Geometry type can't be measured (for example `GeometryCollection`) |
| `INVALID` | Empty or missing geometry |
| `ERROR` | Unexpected failure while measuring this one feature |

If the file isn't `COMPLETED` yet, this endpoint returns `409`.

### `GET /api/files/{id}/features/` – full features (extra)

Same pagination. Returns each feature's index, geometry type, **geometry as GeoJSON**, CRS and properties, so the extracted geometry is available through the API.

---

## Architecture

### Application structure

```
geo-measure-api/
├── app/
│   ├── main.py              # FastAPI app, router registration, DB table creation
│   ├── db.py                # SQLAlchemy engine, session, Base
│   ├── models.py            # UploadedFile and Feature tables
│   ├── schemas.py           # Pydantic response models
│   ├── api/
│   │   └── files.py         # HTTP endpoints (thin: validation, orchestration, persistence)
│   └── services/
│       ├── parser.py        # Read KML / zipped Shapefile into features
│       ├── crs.py           # Choose a projected, metric CRS
│       └── measurements.py  # Area / length calculation
├── tests/                   # Unit and API tests, sample data in tests/data
├── requirements.txt
└── README.md
```

The HTTP layer only validates input, calls the services and stores results. All geospatial logic lives in `services/`, which has no dependency on FastAPI and is tested on its own.

### File-processing flow

1. `POST /api/files/` validates the extension and streams the upload to a temporary directory, enforcing a 50 MB limit. The original filename is never used on disk.
2. A database record is created with status `PROCESSING`.
3. For a `.zip`, the archive is extracted safely (path traversal check, entry count and uncompressed size limits) and the `.shp` is located. KML files are read directly, including every layer/folder they contain.
4. `geopandas` (via `pyogrio`) reads the data. For each feature the parser records its index, geometry type, geometry and properties. Property values are converted to JSON-safe types (NaN becomes `null`, timestamps become ISO strings).
5. Each feature is measured (next section) and stored with its geometry as GeoJSON, CRS, properties and measurement result.
6. The file record is marked `COMPLETED` (or `FAILED` with an error message), and the temporary directory is removed.

### Measurement calculation flow

For each feature, `measure_geometry(geometry, source_crs)`:

1. Returns `INVALID` for empty or missing geometry.
2. Returns `NOT_REQUIRED` for `Point` / `MultiPoint`.
3. Returns `UNSUPPORTED` for anything that isn't a polygon or line type.
4. Otherwise picks a projected CRS, reprojects the geometry, and reads `.area` (polygons) or `.length` (lines) in metres.
5. Any unexpected exception is caught and reported as `ERROR` for that feature only.

### CRS handling

Latitude/longitude degrees are never used for measurements. For each feature:

- If the source CRS is already **projected in metres**, it is used as is.
- Otherwise the feature's **centroid** is converted to longitude/latitude and the matching **WGS 84 / UTM zone** is chosen (`EPSG:326xx` in the northern hemisphere, `EPSG:327xx` in the southern). The geometry is transformed to that zone and measured.

The CRS actually used is returned with each measurement as `projected_crs`. Coordinate order is always handled as x=longitude, y=latitude (`always_xy=True`).

If a Shapefile has no `.prj` file, WGS 84 is assumed only when its coordinates look like valid longitude/latitude, and the response sets `crs_assumed: true`. Otherwise the file is rejected with a clear error. KML is always WGS 84 by specification.

---

## Design decisions

| Decision | Why | Alternatives considered |
|---|---|---|
| **FastAPI** | Little boilerplate, Pydantic validation, automatic Swagger docs | Django + DRF: heavier for a small service with no admin or auth needs |
| **geopandas + pyogrio** for reading | One API for both KML and Shapefile; pyogrio ships with GDAL and avoids a separate GDAL install | `fiona` (older, KML needs driver tweaks), calling `ogr2ogr` directly |
| **Per-feature UTM zone** | Accurate for features within one zone, simple, and works for any location | Single equal-area CRS (simpler, but distorts distances); geodesic calculation with `pyproj.Geod` (most accurate, but a different method for projected inputs) |
| **Geodesic cross-check in tests** | Tests compare UTM results to `pyproj.Geod` within 0.5%, proving the CRS handling is correct | Hard-coded expected numbers |
| **SQLite + SQLAlchemy** | Zero setup for reviewers, and the URL is configurable so Postgres works without code changes | PostGIS (better for spatial queries, but more setup than this task needs) |
| **Geometry stored as GeoJSON in a JSON column** | Simple and portable | WKT / WKB, or PostGIS geometry columns |
| **Synchronous processing** | Files are small, so the response already contains the final status and the code stays simple | Background workers (Celery/RQ) with polling on `status` |
| **Failures recorded per feature and per file** | One bad geometry shouldn't hide the other features, and failed uploads stay inspectable | Reject the whole file on the first error |
| **Pagination and a `/features/` endpoint** | Large files stay manageable, and extracted geometry is accessible | Returning everything in one response |

### Known limitations

- A feature that spans several UTM zones is measured in the zone of its centroid, which is slightly less accurate for very large features.
- Z (altitude) values are ignored; measurements are planar.
- A Shapefile with no `.prj` is only accepted if its coordinates look like longitude/latitude.
- Processing is synchronous and limited to 50 MB per upload.
- `GeometryCollection` features are reported as `UNSUPPORTED`.

---

## Testing

```bash
python -m pytest -v
```

21 tests cover CRS selection, measurements (checked against a geodesic calculation), the parser (KML, Shapefile, missing `.prj`, zip-slip, bad inputs) and the API (upload, info, measurements, pagination, 400/404/422 errors).

---

## What I learned

- Latitude/longitude cannot be used for area or distance. Choosing a projected CRS per feature, and checking it against a geodesic calculation, made the results trustworthy.
- Coordinate order is easy to get wrong. Using `always_xy=True` consistently avoids swapped axes.
- A KML file can contain several layers (folders), so reading only the first layer silently drops features.
- Uploaded archives are untrusted input: extraction needs path checks and size limits.
- Real-world attribute data contains NaN and timestamps that must be converted before they can be stored or returned as JSON.
- Separating HTTP code from geospatial logic made each part easy to test on its own.

## Future scope

- Background processing (Celery/RQ) with polling or webhooks for large files
- PostgreSQL + PostGIS for spatial queries and indexing
- Optional geodesic measurement mode (`pyproj.Geod`) and a choice of target CRS in the request
- Support for more formats: GeoJSON, GeoPackage, KMZ
- Perimeter for polygons, and per-feature validity checks and repair
- Docker image and CI (tests on every push)
- Authentication, per-user file ownership and rate limiting
- File deletion endpoint and automatic cleanup of old uploads
- Option to omit empty KML attributes from `properties`