import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.db import Base, get_db
from app.main import app

SAMPLE_KML = Path(__file__).parent / "data" / "survey.kml"


@pytest.fixture
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _upload_kml(client):
    return client.post(
        "/api/files/",
        files={"file": ("survey.kml", SAMPLE_KML.read_bytes(), "application/vnd.google-earth.kml+xml")},
    )


def test_upload_kml_and_get_info(client):
    resp = _upload_kml(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"] == "survey.kml"
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["status"] == "COMPLETED"

    info = client.get(f"/api/files/{body['id']}/")
    assert info.status_code == 200
    assert info.json()["feature_count"] == 3


def test_measurements(client):
    file_id = _upload_kml(client).json()["id"]
    resp = client.get(f"/api/files/{file_id}/measurements/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3

    by_type = {m["geometry_type"]: m for m in data["measurements"]}
    poly = by_type["Polygon"]
    assert poly["measurement_status"] == "OK"
    assert poly["projected_crs"] == "EPSG:32643"
    assert 1.1e6 < poly["area_sq_m"] < 1.25e6

    line = by_type["LineString"]
    assert 10_000 < line["length_m"] < 11_000

    point = by_type["Point"]
    assert point["measurement_status"] == "NOT_REQUIRED"
    assert "area_sq_m" not in point


def test_measurements_pagination(client):
    file_id = _upload_kml(client).json()["id"]
    data = client.get(f"/api/files/{file_id}/measurements/?limit=1&offset=1").json()
    assert data["total"] == 3
    assert len(data["measurements"]) == 1


def test_upload_zipped_shapefile(client, tmp_path):
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gdf = gpd.GeoDataFrame(
        {"name": ["Plot A"]},
        geometry=[Polygon([(74.0, 19.0), (74.01, 19.0), (74.01, 19.01), (74.0, 19.01)])],
        crs="EPSG:4326",
    )
    gdf.to_file(shp_dir / "plots.shp")
    zip_path = tmp_path / "plots.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in shp_dir.glob("plots.*"):
            zf.write(f, f.name)

    resp = client.post(
        "/api/files/",
        files={"file": ("plots.zip", zip_path.read_bytes(), "application/zip")},
    )
    assert resp.status_code == 201
    assert resp.json()["feature_count"] == 1


def test_rejects_unsupported_extension(client):
    resp = client.post("/api/files/", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert resp.status_code == 400


def test_corrupt_file_returns_422(client):
    resp = client.post("/api/files/", files={"file": ("bad.kml", b"this is not xml", "text/xml")})
    assert resp.status_code == 422
    assert "file_id" in resp.json()["detail"]


def test_unknown_file_returns_404(client):
    assert client.get("/api/files/doesnotexist/").status_code == 404