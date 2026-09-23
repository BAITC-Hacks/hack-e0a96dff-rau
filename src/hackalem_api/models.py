from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Turbine(Base):
    __tablename__ = "turbines"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    measurements: Mapped[list["Measurement"]] = relationship(back_populates="turbine")


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint("turbine_id", "timestamp", name="uq_measurement_turbine_timestamp"),
        CheckConstraint("power >= 0 AND power <= 1", name="ck_measurement_power_normalized"),
        Index("ix_measurements_turbine_timestamp", "turbine_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    turbine_id: Mapped[str] = mapped_column(ForeignKey("turbines.id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    wind_ms: Mapped[float] = mapped_column(Float, nullable=False)
    power: Mapped[float] = mapped_column(Float, nullable=False)
    temp_c: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="uploaded_csv", nullable=False)

    turbine: Mapped[Turbine] = relationship(back_populates="measurements")


class WeatherForecast(Base):
    __tablename__ = "weather_forecasts"
    __table_args__ = (
        UniqueConstraint("turbine_id", "target_time", "lead_hours", "issued_at", name="uq_weather_vintage"),
        CheckConstraint("lead_hours IN (24, 48)", name="ck_weather_lead_hours"),
        Index("ix_weather_target_lead", "target_time", "lead_hours"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    turbine_id: Mapped[str] = mapped_column(ForeignKey("turbines.id", ondelete="CASCADE"), nullable=False)
    target_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    lead_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    wind_speed_100m_ms: Mapped[float | None] = mapped_column(Float)
    wind_direction_100m_deg: Mapped[float | None] = mapped_column(Float)
    temperature_2m_c: Mapped[float | None] = mapped_column(Float)
    relative_humidity_2m_pct: Mapped[float | None] = mapped_column(Float)
    wind_gusts_10m_ms: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(80), default="open-meteo-previous-runs", nullable=False)


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (
        CheckConstraint("horizon_hours IN (24, 48)", name="ck_run_horizon_hours"),
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed')", name="ck_run_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False, index=True)
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_time: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(String(1000))
    model_version: Mapped[str | None] = mapped_column(String(80))
    values: Mapped[list["ForecastValue"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class ForecastValue(Base):
    __tablename__ = "forecast_values"
    __table_args__ = (
        UniqueConstraint("run_id", "turbine_id", "target_time", name="uq_forecast_run_target"),
        CheckConstraint("power >= 0 AND power <= 1", name="ck_forecast_power_normalized"),
        CheckConstraint("horizon_hours >= 1 AND horizon_hours <= 48", name="ck_forecast_value_horizon"),
        Index("ix_forecast_values_run_target", "run_id", "target_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False)
    turbine_id: Mapped[str] = mapped_column(ForeignKey("turbines.id"), nullable=False)
    target_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    power: Mapped[float] = mapped_column(Float, nullable=False)
    wind_speed_100m_ms: Mapped[float | None] = mapped_column(Float)
    temperature_2m_c: Mapped[float | None] = mapped_column(Float)

    run: Mapped[ForecastRun] = relationship(back_populates="values")
