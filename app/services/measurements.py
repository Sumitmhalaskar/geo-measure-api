from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from pyproj import CRS, Transformer

from app.services.crs import get_projected_crs

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString", "LinearRing"}
NO_MEASURE_TYPES = {"Point", "MultiPoint"}


def _project(geom: BaseGeometry, source_crs, target_crs: CRS) -> BaseGeometry:
    source = CRS.from_user_input(source_crs)
    if source == target_crs:
        return geom
    transformer = Transformer.from_crs(source, target_crs, always_xy=True)
    return transform(transformer.transform, geom)


def measure_geometry(geom: BaseGeometry | None, source_crs) -> dict:
    """
    Measure one geometry. Never raises: problems are reported in the result.

    Returns a dict with:
      measurement_status: OK | NOT_REQUIRED | UNSUPPORTED | INVALID | ERROR
      area_sq_m / length_m (when applicable)
      projected_crs: the CRS used for the calculation (when applicable)
      message: explanation when status is not OK
    """
    if geom is None or geom.is_empty:
        return {"measurement_status": "INVALID", "message": "Empty or missing geometry"}

    geom_type = geom.geom_type

    if geom_type in NO_MEASURE_TYPES:
        return {"measurement_status": "NOT_REQUIRED", "message": "No measurement for points"}

    if geom_type not in AREA_TYPES | LENGTH_TYPES:
        return {
            "measurement_status": "UNSUPPORTED",
            "message": f"Measurement not supported for {geom_type}",
        }

    try:
        target_crs = get_projected_crs(geom, source_crs)
        projected = _project(geom, source_crs, target_crs)
        result = {
            "measurement_status": "OK",
            "projected_crs": f"EPSG:{target_crs.to_epsg()}" if target_crs.to_epsg() else target_crs.to_string(),
        }
        if geom_type in AREA_TYPES:
            result["area_sq_m"] = round(projected.area, 4)
        else:
            result["length_m"] = round(projected.length, 4)
        return result
    except Exception as exc:  # one bad feature must not crash the whole file
        return {"measurement_status": "ERROR", "message": str(exc)}