#!/usr/bin/env python3
"""Join turbine hourly targets to archived 24 h / 48 h Open-Meteo forecasts."""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
POWER_FILE = ROOT / "outputs/hourly_power.csv"
OUTPUT_FILE = ROOT / "outputs/hourly_training_weather.csv"
CACHE_DIR = ROOT / "data/weather_cache"
LATITUDE = 43.645150
LONGITUDE = 78.535604
ENDPOINT = "https://previous-runs-api.open-meteo.com/v1/forecast"
BASE_VARIABLES = ["wind_speed_100m", "wind_direction_100m", "temperature_2m", "relative_humidity_2m", "wind_gusts_10m"]
LEADS = (1, 2)


def fetch_weather(start: str, end: str):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"previous_runs_{start}_{end}.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        print(f"Использую кэш погоды: {cache.relative_to(ROOT)}")
        return data

    hourly = [f"{name}_previous_day{lead}" for name in BASE_VARIABLES for lead in LEADS]
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": start,
        "end_date": end,
        "hourly": ",".join(hourly),
        "wind_speed_unit": "ms",
        "timezone": "Asia/Almaty",
    }
    url = ENDPOINT + "?" + urlencode(params)
    result = subprocess.run(["curl", "-fsS", "--max-time", "90", url], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    if data.get("error"):
        raise RuntimeError("Open-Meteo вернул ошибку: " + str(data.get("reason")))
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Скачан и закэширован прогноз: {cache.relative_to(ROOT)}")
    return data


def main():
    if not POWER_FILE.exists():
        raise SystemExit(f"Не найден {POWER_FILE}; сначала запустите scripts/build_hourly_dataset.py")
    with POWER_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        power_rows = list(csv.DictReader(f))
    if not power_rows:
        raise SystemExit("Почасовая таблица пуста")

    timestamps = [datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S") for row in power_rows]
    start, end = min(timestamps).date().isoformat(), max(timestamps).date().isoformat()
    weather = fetch_weather(start, end)
    hourly = weather.get("hourly", {})
    weather_keys = hourly.get("time", [])
    weather_by_time = {}
    names = [f"{name}_previous_day{lead}" for name in BASE_VARIABLES for lead in LEADS]
    for i, api_time in enumerate(weather_keys):
        # Keep local wall-clock labels as supplied by both source files; no UTC conversion.
        stamp = datetime.fromisoformat(api_time).strftime("%Y-%m-%d %H:%M:%S")
        weather_by_time[stamp] = {key: hourly.get(key, [None] * len(weather_keys))[i] for key in names}

    output = []
    weather_hits = {lead: 0 for lead in LEADS}
    wind_hits = {lead: 0 for lead in LEADS}
    timestamp_hits = 0
    for row in power_rows:
        forecast = weather_by_time.get(row["timestamp"], {})
        timestamp_hits += bool(forecast)
        out = {
            "timestamp": row["timestamp"],
            "turbine_id": row["turbine_id"],
            "power": row["power"],
            "observed_wind_ms": row["wind_ms"],
            "observed_temp_c": row["temp_c"],
            "n_samples": row["n_samples"],
        }
        for lead in LEADS:
            lead_keys = [f"{name}_previous_day{lead}" for name in BASE_VARIABLES]
            valid = all(forecast.get(k) is not None for k in lead_keys)
            weather_hits[lead] += valid
            wind_hits[lead] += forecast.get(f"wind_speed_100m_previous_day{lead}") is not None
            for key in lead_keys:
                out[key.replace(f"_previous_day{lead}", f"_lead{lead}d")] = forecast.get(key)
        output.append(out)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    fields = list(output[0])
    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)

    print(f"Создано: {OUTPUT_FILE}")
    print(f"Почасовых target-строк: {len(output):,} (каждая турбина отдельно)")
    print(f"Часов CSV с соответствующей меткой времени в ответе API: {timestamp_hits:,}/{len(power_rows):,}")
    for lead, count in wind_hits.items():
        print(f"Строк с прогнозом скорости ветра lead {lead}d: {count:,}/{len(power_rows):,}")
    for lead, count in weather_hits.items():
        print(f"Полный набор погодных признаков lead {lead}d: {count:,}/{len(power_rows):,} строк")
    print(f"Погодная точка сетки: {weather.get('latitude')}, {weather.get('longitude')} (запрошено {LATITUDE}, {LONGITUDE})")
    print(f"Временная зона ответа API: {weather.get('timezone')}; часовые метки пока сопоставлены как локальные без сдвига.")
    print("Поля observed_wind_ms/observed_temp_c оставлены для проверки качества; их нельзя использовать как будущие признаки модели.")


if __name__ == "__main__":
    main()
