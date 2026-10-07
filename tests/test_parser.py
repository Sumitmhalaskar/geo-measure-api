import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from app.services.parser import GeoFileError, parse_geofile

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <Placemark><name>Plot A</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
    74.0,19.0,0 74.01,19.0,0 74.01,19.01,0 74.0,19.01,0 74.0,19.0,0
  </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  <Placemark><name>Road 1</name><LineString><coordinates>
    74.0,19.0,0 74.1,19.0,0
  </coordinates></LineString></Placemark>
  <Placemark><name>Well</name><Point><coordinates>74.05,19.05,0</coordinates></Point></Placemark>
</Document>
</kml>
"""


def _make_shapefile_zip(tmp_path, with_prj=True):
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gdf = gpd.GeoDataFrame(
        {"name": ["Plot A", "Plot B"]},
        geometry=[
            Polygon([(74.0, 19.0), (74.01, 19.0), (74.01, 19.01), (74.0, 19.01)]),
            Polygon([(74.02, 19.0), (74.03, 19.0), (74.03, 19.01), (74.02, 19.01)]),
        ],
        crs="EPSG:4326",
    )
    gdf.to_file(shp_dir / "plots.shp")
    if not with_prj:
        (shp_dir / "plots.prj").unlink()
    zip_path = tmp_path / "plots.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in shp_dir.glob("plots.*"):
            zf.write(f, f.name)
    return zip_path


def test_parse_kml(tmp_path):
    kml = tmp_path / "survey.kml"
    kml.write_text(KML, encoding="utf-8")

    parsed = parse_geofile(kml, tmp_path / "work")

    assert parsed.crs == "EPSG:4326"
    assert len(parsed.features) == 3
    types = {f.properties["Name"]: f.geometry_type for f in parsed.features}
    assert types == {"Plot A": "Polygon", "Road 1": "LineString", "Well": "Point"}
    assert [f.index for f in parsed.features] == [0, 1, 2]


def test_parse_zipped_shapefile(tmp_path):
    zip_path = _make_shapefile_zip(tmp_path)
    work = tmp_path / "work"
    work.mkdir()

    parsed = parse_geofile(zip_path, work)

    assert parsed.crs == "EPSG:4326"
    assert parsed.crs_assumed is False
    assert len(parsed.features) == 2
    assert parsed.features[0].properties["name"] == "Plot A"
    assert parsed.features[0].geometry_type == "Polygon"


def test_shapefile_without_prj_assumes_wgs84(tmp_path):
    zip_path = _make_shapefile_zip(tmp_path, with_prj=False)
    work = tmp_path / "work"
    work.mkdir()

    parsed = parse_geofile(zip_path, work)

    assert parsed.crs == "EPSG:4326"
    assert parsed.crs_assumed is True


def test_zip_without_shp_is_rejected(tmp_path):
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "no shapefile here")
    work = tmp_path / "work"
    work.mkdir()

    with pytest.raises(GeoFileError):
        parse_geofile(zip_path, work)


def test_zip_slip_is_rejected(tmp_path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.shp", "x")
    work = tmp_path / "work"
    work.mkdir()

    with pytest.raises(GeoFileError):
        parse_geofile(zip_path, work)


def test_unsupported_extension_is_rejected(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("hello")
    with pytest.raises(GeoFileError):
        parse_geofile(f, tmp_path)