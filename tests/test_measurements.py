import pytest
from pyproj import Geod
from shapely.geometry import (
    GeometryCollection, LineString, Point, Polygon,
)

from app.services.measurements import measure_geometry

GEOD = Geod(ellps="WGS84")


def test_polygon_area_matches_geodesic():
    poly = Polygon([(74.0, 19.0), (74.01, 19.0), (74.01, 19.01), (74.0, 19.01)])
    result = measure_geometry(poly, "EPSG:4326")

    expected = abs(GEOD.geometry_area_perimeter(poly)[0])
    assert result["measurement_status"] == "OK"
    assert result["projected_crs"] == "EPSG:32643"
    assert result["area_sq_m"] == pytest.approx(expected, rel=0.005)


def test_line_length_matches_geodesic():
    line = LineString([(74.0, 19.0), (74.1, 19.0)])
    result = measure_geometry(line, "EPSG:4326")

    expected = GEOD.geometry_length(line)
    assert result["measurement_status"] == "OK"
    assert result["length_m"] == pytest.approx(expected, rel=0.005)


def test_point_needs_no_measurement():
    result = measure_geometry(Point(74.0, 19.0), "EPSG:4326")
    assert result["measurement_status"] == "NOT_REQUIRED"


def test_unsupported_geometry_is_handled():
    coll = GeometryCollection([Point(74.0, 19.0), LineString([(74, 19), (74.1, 19)])])
    result = measure_geometry(coll, "EPSG:4326")
    assert result["measurement_status"] == "UNSUPPORTED"


def test_empty_geometry_is_handled():
    assert measure_geometry(None, "EPSG:4326")["measurement_status"] == "INVALID"
    assert measure_geometry(Polygon(), "EPSG:4326")["measurement_status"] == "INVALID"