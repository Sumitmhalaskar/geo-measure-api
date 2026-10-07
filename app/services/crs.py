from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry


def _is_metric(crs: CRS) -> bool:
    """True if the CRS is projected and its units are metres."""
    if not crs.is_projected:
        return False
    return crs.axis_info[0].unit_name.lower() in ("metre", "meter")


def utm_crs_for_lonlat(lon: float, lat: float) -> CRS:
    """Return the WGS84 UTM zone CRS that contains the given lon/lat."""
    zone = int((lon + 180) // 6) + 1
    zone = min(max(zone, 1), 60)
    epsg = (32600 if lat >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def get_projected_crs(geom: BaseGeometry, source_crs) -> CRS:
    """
    Pick a metric projected CRS for measuring this geometry.

    - If the source CRS is already projected in metres, use it as is.
    - Otherwise, find the geometry's centroid in lon/lat and use the
      UTM zone for that location.
    """
    source = CRS.from_user_input(source_crs)

    if _is_metric(source):
        return source

    centroid = geom.centroid
    to_wgs84 = Transformer.from_crs(source, "EPSG:4326", always_xy=True)
    lon, lat = to_wgs84.transform(centroid.x, centroid.y)
    return utm_crs_for_lonlat(lon, lat)