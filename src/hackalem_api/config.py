from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str = f"sqlite:///{ROOT / 'data/hackalem.db'}"
    forecast_csv_path: Path = ROOT / "outputs/forecast_48h.csv"
    hourly_csv_path: Path = ROOT / "outputs/hourly_power.csv"
    model_path: Path = ROOT / "outputs/catboost_power.cbm"
    metrics_path: Path = ROOT / "outputs/metrics.json"
    weather_cache_dir: Path = ROOT / "data/weather_cache"
    max_upload_bytes: int = 25 * 1024 * 1024
    app_name: str = "HackAlem Wind Forecast API"
    app_version: str = "0.2.0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
