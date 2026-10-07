from shapely.geometry import Point

from app.services.crs import get_projected_crs, utm_crs_for_lonlat


def test_utm_zone_for_india():
    # Longitude ~74.7 falls in UTM zone 43 north
    crs = get_projected_crs(Point(74.74, 19.09), "EPSG:4326")
    assert crs.to_epsg() == 32643


def test_southern_hemisphere_uses_327xx():
    crs = utm_crs_for_lonlat(151.2, -33.9)  # Sydney
    assert crs.to_epsg() == 32756


def test_projected_metric_crs_is_kept():
    crs = get_projected_crs(Point(500000, 2000000), "EPSG:32643")
    assert crs.to_epsg() == 32643