"""Read archived sensor observations and perform coordinate-specific model inference."""
import csv
import hashlib
import json
import math
import subprocess
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import urlencode

from pydantic import BaseModel, Field
from typing import Literal


TURBINES = [
    {"id": "1", "name": "Турбина 01", "latitude": 43.645150, "longitude": 78.535604},
    {"id": "2", "name": "Турбина 02", "latitude": 43.643198, "longitude": 78.538828},
]
ISSUE = datetime(2026, 2, 1)
WEATHER_FIELDS = ["wind_speed_100m", "wind_direction_100m", "temperature_2m", "relative_humidity_2m", "wind_gusts_10m"]


class LocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    horizon_hours: Literal[24, 48] = 48
    reference_turbine_id: Literal["1", "2"] = "1"


@lru_cache(maxsize=8)
def _csv(path, modified):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def read_rows(path):
    return _csv(str(path), path.stat().st_mtime_ns)


def dashboard_data(settings):
    observed = read_rows(settings.hourly_csv_path)
    predictions = read_rows(settings.forecast_csv_path)
    turbines = []
    for station in TURBINES:
        history = sorted((r for r in observed if r["turbine_id"] == station["id"]), key=lambda r: r["timestamp"])[-24:]
        snapshot = None
        if history:
            last = history[-1]
            snapshot = {"timestamp": last["timestamp"], "power": float(last["power"]),
                        "wind_ms": float(last["wind_ms"]), "temperature_c": float(last["temp_c"]),
                        "samples": int(last["n_samples"])}
        forecast = [{"target_time": r["target_time"], "horizon_hours": int(r["horizon_hours"]),
                     "power": float(r["forecast_power"]), "wind_ms": float(r["wind_speed_100m_ms"]),
                     "temperature_c": float(r["temperature_2m_c"])}
                    for r in predictions if r["turbine_id"] == station["id"]]
        turbines.append({**station, "mode": "archive", "snapshot": snapshot,
                         "history": [{"timestamp": r["timestamp"], "power": float(r["power"])} for r in history],
                         "forecast": forecast})
    metrics = json.loads(settings.metrics_path.read_text()) if settings.metrics_path.exists() else None
    return {"issue_time": predictions[0]["issue_time"] if predictions else ISSUE.isoformat(),
            "timezone": "Asia/Almaty", "turbines": turbines, "metrics": metrics,
            "mode": "archive", "power_unit": "fraction_of_rated_capacity"}


def get_weather(settings, request):
    # Include coordinates, variables and dates in the key: a new location must not reuse another location's weather.
    parameters = {"latitude": request.latitude, "longitude": request.longitude,
                  "start_date": "2026-02-01", "end_date": "2026-02-03", "timezone": "Asia/Almaty",
                  "wind_speed_unit": "ms", "hourly": ",".join(f"{name}_previous_day{day}" for name in WEATHER_FIELDS for day in (1, 2))}
    key = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()[:24]
    settings.weather_cache_dir.mkdir(parents=True, exist_ok=True)
    cache = settings.weather_cache_dir / f"location_{key}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    result = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--max-time", "30",
                             "https://previous-runs-api.open-meteo.com/v1/forecast?" + urlencode(parameters)],
                            capture_output=True, text=True, timeout=35, check=True)
    data = json.loads(result.stdout)
    if data.get("error") or "hourly" not in data:
        raise ValueError("Источник погоды не вернул почасовой прогноз для этих координат.")
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


@lru_cache(maxsize=2)
def load_model(path, modified):
    from catboost import CatBoostRegressor
    model = CatBoostRegressor()
    model.load_model(path)
    return model


def coordinate_forecast(settings, request):
    weather = get_weather(settings, request)
    hours = weather["hourly"]
    indices = {datetime.fromisoformat(t): i for i, t in enumerate(hours["time"])}
    model = load_model(str(settings.model_path), settings.model_path.stat().st_mtime_ns)
    rows, features = [], []
    for h in range(1, request.horizon_hours + 1):
        time = ISSUE + timedelta(hours=h)
        index = indices.get(time)
        day = 1 if h <= 24 else 2
        if index is None:
            raise ValueError("В архиве отсутствует часть нужных часов.")
        values = {name: hours.get(f"{name}_previous_day{day}", [None] * len(indices))[index] for name in WEATHER_FIELDS}
        if any(values[name] is None for name in WEATHER_FIELDS):
            raise ValueError("Архив погоды для этих координат неполон. Выберите другую точку.")
        direction = math.radians(values["wind_direction_100m"])
        features_by_name = {
            "turbine_id": request.reference_turbine_id, "lead_hours": day * 24,
            "hour_sin": math.sin(2 * math.pi * time.hour / 24), "hour_cos": math.cos(2 * math.pi * time.hour / 24),
            "weekday_sin": math.sin(2 * math.pi * time.weekday() / 7), "weekday_cos": math.cos(2 * math.pi * time.weekday() / 7),
            "month_sin": math.sin(2 * math.pi * (time.month - 1) / 12), "month_cos": math.cos(2 * math.pi * (time.month - 1) / 12),
            "wind_speed_100m": values["wind_speed_100m"], "wind_direction_sin": math.sin(direction),
            "wind_direction_cos": math.cos(direction), "temperature_2m": values["temperature_2m"],
            "relative_humidity_2m": values["relative_humidity_2m"], "wind_gusts_10m": values["wind_gusts_10m"],
            # No observed sensors or power lags exist for a user-entered site.
            "power_at_issue": math.nan, "power_24h_before_issue": math.nan,
        }
        features.append([features_by_name[name] for name in model.feature_names_])
        rows.append({"target_time": time.strftime("%Y-%m-%d %H:%M:%S"), "horizon_hours": h,
                     "wind_ms": values["wind_speed_100m"], "temperature_c": values["temperature_2m"]})
    for row, prediction in zip(rows, model.predict(features)):
        row["power"] = round(max(0.0, min(1.0, float(prediction))), 6)
    return {"id": "custom", "name": "Новая площадка", "mode": "scenario", "latitude": request.latitude,
            "longitude": request.longitude, "reference_turbine_id": request.reference_turbine_id,
            "snapshot": None, "history": [], "forecast": rows, "issue_time": ISSUE.isoformat(),
            "weather_grid": {"latitude": weather.get("latitude"), "longitude": weather.get("longitude")},
            "notice": "Оценка по модели двух исходных турбин. Для новой площадки точность не проверена; показания датчиков отсутствуют."}
