#!/usr/bin/env python3
"""Train/backtest CatBoost on archived forecast vintages and write a 48 h forecast."""

from __future__ import annotations

import csv
import json
import math
import bisect
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from catboost import CatBoostRegressor, Pool


ROOT = Path(__file__).resolve().parents[1]
JOINED = ROOT / "outputs/hourly_training_weather.csv"
POWER = ROOT / "outputs/hourly_power.csv"
OUT = ROOT / "outputs"
CACHE = ROOT / "data/weather_cache"
MODEL_PATH = OUT / "catboost_power.cbm"
BACKTEST_MODEL_PATH = OUT / "catboost_backtest.cbm"
METRICS_PATH = OUT / "metrics.json"
BACKTEST_PATH = OUT / "backtest_predictions.csv"
FORECAST_PATH = OUT / "forecast_48h.csv"
FORECAST_JSON = OUT / "forecast_48h.json"
API = "https://previous-runs-api.open-meteo.com/v1/forecast"
LATITUDE, LONGITUDE = 43.645150, 78.535604
BASE_WEATHER = ["wind_speed_100m", "wind_direction_100m", "temperature_2m", "relative_humidity_2m", "wind_gusts_10m"]
FEATURES = [
    "turbine_id", "lead_hours", "hour_sin", "hour_cos", "weekday_sin", "weekday_cos", "month_sin", "month_cos",
    "wind_speed_100m", "wind_direction_sin", "wind_direction_cos", "temperature_2m", "relative_humidity_2m", "wind_gusts_10m",
    "power_at_issue", "power_24h_before_issue",
]
CAT_FEATURES = [0]
VALIDATION_START = datetime(2025, 10, 1)
FORECAST_ISSUE = datetime(2026, 2, 1, 0)


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def num(value):
    if value in (None, ""):
        return math.nan
    return float(value)


def features_for(turbine_id, target_time: datetime, lead: int, values: dict, power_at_issue=None, power_24h_before_issue=None):
    hour_angle = 2 * math.pi * target_time.hour / 24
    weekday_angle = 2 * math.pi * target_time.weekday() / 7
    month_angle = 2 * math.pi * (target_time.month - 1) / 12
    direction = num(values.get("wind_direction_100m"))
    if math.isnan(direction):
        direction_sin = direction_cos = math.nan
    else:
        direction_sin = math.sin(math.radians(direction))
        direction_cos = math.cos(math.radians(direction))
    return [
        str(turbine_id), float(lead), math.sin(hour_angle), math.cos(hour_angle),
        math.sin(weekday_angle), math.cos(weekday_angle), math.sin(month_angle), math.cos(month_angle),
        num(values.get("wind_speed_100m")), direction_sin, direction_cos,
        num(values.get("temperature_2m")), num(values.get("relative_humidity_2m")), num(values.get("wind_gusts_10m")),
        power_at_issue if power_at_issue is not None else math.nan,
        power_24h_before_issue if power_24h_before_issue is not None else math.nan,
    ]


def weather_values(row, lead):
    suffix = f"_lead{lead // 24}d"
    return {name: row.get(name + suffix) for name in BASE_WEATHER}


def last_known(power_history, turbine_id, at_or_before):
    timestamps, powers = power_history.get(turbine_id, ([], []))
    index = bisect.bisect_right(timestamps, at_or_before) - 1
    return powers[index] if index >= 0 else None


def make_examples(joined_rows, power_history, power_lookup):
    examples = []
    for row in joined_rows:
        target_time = dt(row["timestamp"])
        turbine = row["turbine_id"]
        actual = float(row["power"])
        for lead in (24, 48):
            weather = weather_values(row, lead)
            # Wind speed is required to identify an archived forecast; other features may be null.
            if weather["wind_speed_100m"] in (None, ""):
                continue
            issue_time = target_time - timedelta(hours=lead)
            persistence = last_known(power_history, turbine, issue_time)
            power_lag_24 = last_known(power_history, turbine, issue_time - timedelta(hours=24))
            yesterday = power_lookup.get((turbine, target_time - timedelta(hours=24)))
            two_days_prior = power_lookup.get((turbine, target_time - timedelta(hours=48)))
            examples.append({
                "time": target_time,
                "turbine": turbine,
                "lead": lead,
                "actual": actual,
                "features": features_for(turbine, target_time, lead, weather, persistence, power_lag_24),
                "persistence": persistence,
                "same_hour_yesterday": yesterday if lead == 24 else None,
                "same_hour_two_days_prior": two_days_prior if lead == 48 else None,
            })
    return examples


def calc_metrics(pairs):
    if not pairs:
        return {"n": 0, "mae": None, "rmse": None}
    errors = [float(pred) - float(actual) for actual, pred in pairs]
    return {"n": len(errors), "mae": sum(abs(e) for e in errors) / len(errors), "rmse": math.sqrt(sum(e * e for e in errors) / len(errors))}


def summarize(predictions):
    result = {"overall": {}, "by_horizon_hours": {}}
    for model_key, output_key in (("catboost", "catboost"), ("persistence_at_issue", "persistence_at_issue")):
        result["overall"][output_key] = calc_metrics([(r["actual_power"], r[model_key]) for r in predictions if r[model_key] is not None])
    for lead in (24, 48):
        subset = [r for r in predictions if r["lead_hours"] == lead]
        scores = {
            key: calc_metrics([(r["actual_power"], r[model]) for r in subset if r[model] is not None])
            for key, model in (("catboost", "catboost"), ("persistence_at_issue", "persistence_at_issue"))
        }
        seasonal_key = "same_hour_yesterday" if lead == 24 else "same_hour_two_days_prior"
        scores[seasonal_key] = calc_metrics([(r["actual_power"], r[seasonal_key]) for r in subset if r[seasonal_key] is not None])
        result["by_horizon_hours"][str(lead)] = scores
    return result


def fetch_future_weather():
    start = (FORECAST_ISSUE + timedelta(hours=1)).date().isoformat()
    end = (FORECAST_ISSUE + timedelta(hours=48)).date().isoformat()
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"forecast_issue_{FORECAST_ISSUE:%Y%m%d%H}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    hourly = [f"{name}_previous_day{lead}" for name in BASE_WEATHER for lead in (1, 2)]
    params = {"latitude": LATITUDE, "longitude": LONGITUDE, "start_date": start, "end_date": end,
              "hourly": ",".join(hourly), "wind_speed_unit": "ms", "timezone": "Asia/Almaty"}
    result = subprocess.run(["curl", "-fsS", "--max-time", "90", API + "?" + urlencode(params)],
                            check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    if data.get("error"):
        raise RuntimeError("Open-Meteo forecast request failed: " + str(data.get("reason")))
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not JOINED.exists() or not POWER.exists():
        raise SystemExit("Сначала запустите build_hourly_dataset.py и join_weather_data.py")
    joined_rows = read_csv(JOINED)
    power_rows = read_csv(POWER)
    power_lookup = {(r["turbine_id"], dt(r["timestamp"])): float(r["power"]) for r in power_rows}
    power_history = {}
    for turbine_id in sorted({r["turbine_id"] for r in power_rows}):
        turbine_rows = sorted((dt(r["timestamp"]), float(r["power"])) for r in power_rows if r["turbine_id"] == turbine_id)
        power_history[turbine_id] = ([x[0] for x in turbine_rows], [x[1] for x in turbine_rows])
    examples = make_examples(joined_rows, power_history, power_lookup)
    train = [e for e in examples if e["time"] < VALIDATION_START]
    valid = [e for e in examples if VALIDATION_START <= e["time"] < FORECAST_ISSUE]
    if not train or not valid:
        raise SystemExit(f"Недостаточно train/validation данных: train={len(train)}, validation={len(valid)}")

    train_pool = Pool([e["features"] for e in train], [e["actual"] for e in train],
                      cat_features=CAT_FEATURES, feature_names=FEATURES)
    valid_pool = Pool([e["features"] for e in valid], [e["actual"] for e in valid],
                      cat_features=CAT_FEATURES, feature_names=FEATURES)
    model = CatBoostRegressor(iterations=800, depth=7, learning_rate=0.04, loss_function="MAE",
                              eval_metric="MAE", l2_leaf_reg=5, random_seed=42,
                              allow_writing_files=False, verbose=100)
    model.fit(train_pool, eval_set=valid_pool, early_stopping_rounds=60, verbose=100)
    model.save_model(str(BACKTEST_MODEL_PATH))

    predictions = []
    yhat = model.predict(valid_pool)
    for example, estimate in zip(valid, yhat):
        predictions.append({
            "timestamp": example["time"].strftime("%Y-%m-%d %H:%M:%S"),
            "turbine_id": example["turbine"],
            "lead_hours": example["lead"],
            "actual_power": example["actual"],
            "catboost": max(0.0, min(1.0, float(estimate))),
            "persistence_at_issue": example["persistence"],
            "same_hour_yesterday": example["same_hour_yesterday"],
            "same_hour_two_days_prior": example["same_hour_two_days_prior"],
        })
    metrics = summarize(predictions)
    metrics.update({"primary_metric": "MAE", "additional_metric": "RMSE", "validation_start": VALIDATION_START.isoformat(),
                    "validation_end_exclusive": FORECAST_ISSUE.isoformat(), "training_examples": len(train),
                    "validation_examples": len(valid), "best_iteration": int(model.best_iteration_),
                    "february_2026_actuals_used_for_training_or_validation": False})
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    with BACKTEST_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)

    # After measuring the untouched temporal holdout, refit the delivery model
    # on every eligible observation available before the February test window.
    final_pool = Pool([e["features"] for e in examples if e["time"] < FORECAST_ISSUE],
                      [e["actual"] for e in examples if e["time"] < FORECAST_ISSUE],
                      cat_features=CAT_FEATURES, feature_names=FEATURES)
    final_iterations = max(100, int(model.best_iteration_) + 1)
    final_model = CatBoostRegressor(iterations=final_iterations, depth=7, learning_rate=0.04,
                                    loss_function="MAE", eval_metric="MAE", l2_leaf_reg=5,
                                    random_seed=42, allow_writing_files=False, verbose=100)
    final_model.fit(final_pool, verbose=100)
    final_model.save_model(str(MODEL_PATH))

    # Forecast the next 48 hours from 2026-02-01 00:00 local. The archived day-1
    # weather vintage drives hours 1..24; day-2 vintage drives hours 25..48.
    future = fetch_future_weather()
    wh = future["hourly"]
    out_weather = {datetime.fromisoformat(t).strftime("%Y-%m-%d %H:%M:%S"): i for i, t in enumerate(wh["time"])}
    forecast_rows = []
    for h in range(1, 49):
        target = FORECAST_ISSUE + timedelta(hours=h)
        lead = 24 if h <= 24 else 48
        idx = out_weather.get(target.strftime("%Y-%m-%d %H:%M:%S"))
        if idx is None:
            raise RuntimeError(f"Нет погодного прогноза на {target}")
        vals = {name: wh.get(f"{name}_previous_day{lead // 24}", [None] * len(wh["time"]))[idx] for name in BASE_WEATHER}
        if vals["wind_speed_100m"] is None:
            raise RuntimeError(f"Нет архивного прогноза ветра на {target}, lead={lead}h")
        for turbine_id in ("1", "2"):
            power_at_issue = last_known(power_history, turbine_id, FORECAST_ISSUE)
            power_before_issue = last_known(power_history, turbine_id, FORECAST_ISSUE - timedelta(hours=24))
            features = features_for(turbine_id, target, lead, vals, power_at_issue, power_before_issue)
            pred = float(final_model.predict([features])[0])
            forecast_rows.append({"issue_time": FORECAST_ISSUE.strftime("%Y-%m-%d %H:%M:%S"),
                                  "target_time": target.strftime("%Y-%m-%d %H:%M:%S"),
                                  "horizon_hours": h, "turbine_id": turbine_id, "forecast_power": round(max(0.0, min(1.0, pred)), 6),
                                  "weather_lead_hours": lead,
                                  "wind_speed_100m_ms": vals["wind_speed_100m"],
                                  "temperature_2m_c": vals["temperature_2m"]})
    with FORECAST_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(forecast_rows[0]))
        writer.writeheader()
        writer.writerows(forecast_rows)
    FORECAST_JSON.write_text(json.dumps({"issue_time": FORECAST_ISSUE.strftime("%Y-%m-%d %H:%M:%S"),
                                        "timezone": "Asia/Almaty", "model": "CatBoostRegressor",
                                        "forecast_rows": forecast_rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"train={len(train):,}; validation={len(valid):,}; best_iteration={model.best_iteration_}")
    print("Validation metrics:")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Model: {MODEL_PATH}")
    print(f"Backtest: {BACKTEST_PATH}")
    print(f"48h forecast: {FORECAST_PATH} and {FORECAST_JSON} ({len(forecast_rows)} turbine-hour rows)")


if __name__ == "__main__":
    main()
