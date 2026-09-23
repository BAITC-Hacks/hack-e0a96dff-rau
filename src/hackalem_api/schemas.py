from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ForecastRunCreate(BaseModel):
    horizon_hours: Literal[24, 48]
    turbine_ids: list[str] | None = Field(default=None, min_length=1)


class ForecastRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    horizon_hours: int
    issue_time: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    model_version: str | None
    result_count: int = 0


class ForecastValueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    turbine_id: str
    target_time: datetime
    horizon_hours: int
    power: float
    wind_speed_100m_ms: float | None
    temperature_2m_c: float | None


class CsvValidationRead(BaseModel):
    valid: bool
    rows: int
    unique_turbines: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    errors: list[str]
    warnings: list[str]


class HealthRead(BaseModel):
    status: str
    database: str
