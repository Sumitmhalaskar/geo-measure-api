import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from shapely.geometry import mapping
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Feature, UploadedFile
from app.schemas import FeaturesResponse, FileInfo, MeasurementsResponse
from app.services.measurements import measure_geometry
from app.services.parser import GeoFileError, parse_geofile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_SUFFIXES = {".kml", ".zip"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def _save_upload(upload: UploadFile, dest: Path) -> None:
    """Stream the upload to disk, enforcing a size limit."""
    size = 0
    with dest.open("wb") as out:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "File is too large (max 50 MB)")
            out.write(chunk)


def _get_file_or_404(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(404, "File not found")
    return record


def _page_of_features(db: Session, record: UploadedFile, limit: int, offset: int):
    if record.status != "COMPLETED":
        raise HTTPException(409, f"File is not ready (status: {record.status})")
    total = db.scalar(
        select(func.count()).select_from(Feature).where(Feature.file_id == record.id)
    )
    rows = db.scalars(
        select(Feature)
        .where(Feature.file_id == record.id)
        .order_by(Feature.feature_index)
        .limit(limit)
        .offset(offset)
    ).all()
    return total, rows


@router.post("/", response_model=FileInfo, response_model_exclude_none=True, status_code=201)
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a .kml or a .zip containing a shapefile, then process it."""
    original_name = Path(file.filename or "").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, "Unsupported file type. Upload a .kml or a .zip containing a shapefile")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        saved = tmp_path / f"upload{suffix}"
        _save_upload(file, saved)

        record = UploadedFile(
            id=uuid.uuid4().hex,
            filename=original_name,
            file_type=suffix.lstrip("."),
            status="PROCESSING",
        )
        db.add(record)
        db.commit()

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        try:
            parsed = parse_geofile(saved, extract_dir)
        except GeoFileError as exc:
            record.status = "FAILED"
            record.error_message = str(exc)
            db.commit()
            raise HTTPException(422, detail={"message": str(exc), "file_id": record.id})
        except Exception:
            logger.exception("Unexpected error while processing %s", record.id)
            record.status = "FAILED"
            record.error_message = "Unexpected error while processing the file"
            db.commit()
            raise HTTPException(500, detail={"message": record.error_message, "file_id": record.id})

    features = []
    for f in parsed.features:
        m = measure_geometry(f.geometry, parsed.crs)
        features.append(
            Feature(
                file_id=record.id,
                feature_index=f.index,
                geometry_type=f.geometry_type,
                geometry=mapping(f.geometry) if f.geometry is not None else None,
                crs=parsed.crs,
                properties=f.properties,
                measurement_status=m["measurement_status"],
                area_sq_m=m.get("area_sq_m"),
                length_m=m.get("length_m"),
                projected_crs=m.get("projected_crs"),
                message=m.get("message"),
            )
        )
    db.add_all(features)

    record.crs = parsed.crs
    record.crs_assumed = parsed.crs_assumed
    record.feature_count = len(features)
    record.status = "COMPLETED"
    db.commit()
    return record


@router.get("/{file_id}/", response_model=FileInfo, response_model_exclude_none=True)
def get_file(file_id: str, db: Session = Depends(get_db)):
    """Basic information about an uploaded file."""
    return _get_file_or_404(db, file_id)


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    response_model_exclude_none=True,
)
def get_measurements(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Area / length for every feature in the file (paginated)."""
    record = _get_file_or_404(db, file_id)
    total, rows = _page_of_features(db, record, limit, offset)
    return {"file_id": record.id, "total": total, "limit": limit, "offset": offset, "measurements": rows}


@router.get("/{file_id}/features/", response_model=FeaturesResponse)
def get_features(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Full feature details, including geometry as GeoJSON (paginated)."""
    record = _get_file_or_404(db, file_id)
    total, rows = _page_of_features(db, record, limit, offset)
    return {"file_id": record.id, "total": total, "limit": limit, "offset": offset, "features": rows}