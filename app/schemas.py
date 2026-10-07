from typing import Any

from pydantic import BaseModel, ConfigDict


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    feature_count: int
    crs: str | None = None
    crs_assumed: bool = False
    status: str
    error_message: str | None = None


class FeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feature_index: int
    geometry_type: str | None = None
    geometry: dict[str, Any] | None = None
    crs: str
    properties: dict[str, Any]


class MeasurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feature_index: int
    geometry_type: str | None = None
    crs: str
    properties: dict[str, Any]
    measurement_status: str
    area_sq_m: float | None = None
    length_m: float | None = None
    projected_crs: str | None = None
    message: str | None = None


class MeasurementsResponse(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    measurements: list[MeasurementOut]


class FeaturesResponse(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    features: list[FeatureOut]