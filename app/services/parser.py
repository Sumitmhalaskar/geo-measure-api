import math
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

MAX_ZIP_ENTRIES = 100
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB, guards against zip bombs


class GeoFileError(Exception):
    """Raised when an uploaded geospatial file can't be read."""


@dataclass
class ParsedFeature:
    index: int
    geometry_type: str | None
    geometry: BaseGeometry | None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedFile:
    crs: str
    crs_assumed: bool
    features: list[ParsedFeature]


def extract_shapefile_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Safely extract a zip and return the path of the .shp inside it."""
    dest = Path(dest_dir).resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise GeoFileError("Zip contains too many files")
            if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
                raise GeoFileError("Zip is too large when uncompressed")
            for info in infos:
                target = (dest / info.filename).resolve()
                if not target.is_relative_to(dest):  # zip-slip protection
                    raise GeoFileError("Zip contains an unsafe file path")
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise GeoFileError("File is not a valid zip archive") from exc

    shp_files = sorted(
        p for p in dest.rglob("*.shp")
        if "__MACOSX" not in p.parts and not p.name.startswith("._")
    )
    if not shp_files:
        raise GeoFileError("No .shp file found inside the zip")
    return shp_files[0]


def _to_jsonable(value: Any) -> Any:
    """Convert pandas/numpy values to plain JSON-safe Python values."""
    if value is None:
        return None
    if not isinstance(value, (list, dict, tuple)) and pd.isna(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()  # numpy scalar -> python scalar
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _read_frame(path: Path) -> gpd.GeoDataFrame:
    suffix = path.suffix.lower()
    if suffix == ".kml":
        # A KML file can hold several folders; each shows up as a layer.
        layer_names = [row[0] for row in pyogrio.list_layers(path)]
        frames = [gpd.read_file(path, layer=name, engine="pyogrio") for name in layer_names]
        frames = [f for f in frames if len(f) > 0]
        if not frames:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        gdf = pd.concat(frames, ignore_index=True)
        return gpd.GeoDataFrame(gdf, geometry="geometry", crs=frames[0].crs)
    return gpd.read_file(path, engine="pyogrio")


def _crs_to_string(crs: CRS) -> str:
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.to_string()


def read_geofile(path: Path) -> ParsedFile:
    """Read a .kml or .shp file into a ParsedFile."""
    try:
        gdf = _read_frame(Path(path))
    except Exception as exc:
        raise GeoFileError(f"Could not read geospatial data: {exc}") from exc

    crs_assumed = False
    if gdf.crs is None:
        # KML is always WGS84. A shapefile with no .prj is only accepted
        # if its coordinates look like longitude/latitude.
        minx, miny, maxx, maxy = gdf.total_bounds if len(gdf) else (0, 0, 0, 0)
        if Path(path).suffix.lower() == ".kml" or (
            -180 <= minx and maxx <= 180 and -90 <= miny and maxy <= 90
        ):
            gdf = gdf.set_crs("EPSG:4326")
            crs_assumed = True
        else:
            raise GeoFileError("File has no CRS (missing .prj) and coordinates are not lon/lat")

    geom_col = gdf.geometry.name
    features = []
    for i, (_, row) in enumerate(gdf.iterrows()):
        geom = row[geom_col]
        if geom is not None and geom.is_empty:
            geom = None
        properties = {k: _to_jsonable(v) for k, v in row.items() if k != geom_col}
        features.append(
            ParsedFeature(
                index=i,
                geometry_type=geom.geom_type if geom is not None else None,
                geometry=geom,
                properties=properties,
            )
        )

    return ParsedFile(crs=_crs_to_string(gdf.crs), crs_assumed=crs_assumed, features=features)


def parse_geofile(path: Path, workdir: Path) -> ParsedFile:
    """Entry point: accepts a .kml or a .zip containing a shapefile."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".kml":
        return read_geofile(path)
    if suffix == ".zip":
        return read_geofile(extract_shapefile_zip(path, workdir))
    raise GeoFileError("Unsupported file type. Upload a .kml or a .zip containing a shapefile")