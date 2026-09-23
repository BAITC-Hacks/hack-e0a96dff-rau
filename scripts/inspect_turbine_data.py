#!/usr/bin/env python3
"""Audit HackAlem turbine CSV files using only Python's standard library."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_DIR = Path.home() / "Downloads"
DEFAULT_FILES = [
    DEFAULT_DIR / "Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine 1.csv",
    DEFAULT_DIR / "Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine 2.csv",
]
TIME_COL = "Статистическое время"
VALUE_COLS = [
    "Средняя скорость ветра(m/s)",
    "Нормализованная активная мощность",
    "Средняя температура окружающей среды(°C)",
]
STEP = timedelta(minutes=10)


def load_csv(path: Path):
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                sample = f.read(8192)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(f, dialect=dialect)
                rows = list(reader)
                return reader.fieldnames or [], rows, dialect.delimiter, encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("Не удалось прочитать файл как UTF-8 или Windows-1251")


def parse_time(value: str):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def inspect(path: Path):
    if not path.exists():
        print(f"\nФАЙЛ НЕ НАЙДЕН: {path}")
        return None
    headers, rows, delimiter, encoding = load_csv(path)
    missing_columns = [c for c in [TIME_COL, *VALUE_COLS] if c not in headers]
    print(f"\n## {path.name}")
    print(f"Строк: {len(rows):,} | разделитель: {delimiter!r} | кодировка: {encoding}")
    print("Колонки: " + ", ".join(headers))
    if missing_columns:
        print("ОШИБКА: нет обязательных колонок: " + ", ".join(missing_columns))
        return None

    timestamps = []
    bad_times = 0
    missing = Counter()
    bad_numbers = Counter()
    extrema = {c: [float("inf"), float("-inf")] for c in VALUE_COLS}
    hourly_counts = Counter()
    power_outside = 0
    negative_power = 0

    for row in rows:
        ts = parse_time(row.get(TIME_COL, ""))
        if ts is None:
            bad_times += 1
        else:
            timestamps.append(ts)
            hourly_counts[ts.replace(minute=0, second=0, microsecond=0)] += 1
        nums = {}
        for col in VALUE_COLS:
            raw = (row.get(col) or "").strip()
            if not raw:
                missing[col] += 1
                continue
            try:
                nums[col] = float(raw.replace(",", "."))
            except ValueError:
                bad_numbers[col] += 1
                continue
            extrema[col][0] = min(extrema[col][0], nums[col])
            extrema[col][1] = max(extrema[col][1], nums[col])
        p = nums.get("Нормализованная активная мощность")
        if p is not None:
            negative_power += p < 0
            power_outside += not 0 <= p <= 1

    timestamps.sort()
    unique = set(timestamps)
    dupes = len(timestamps) - len(unique)
    gaps = []
    off_grid = 0
    for a, b in zip(timestamps, timestamps[1:]):
        delta = b - a
        if delta > STEP:
            gaps.append((a, b, int(delta.total_seconds() // 60)))
    for ts in unique:
        if ts.minute % 10 or ts.second or ts.microsecond:
            off_grid += 1

    print(f"Период: {timestamps[0] if timestamps else 'нет времени'} — {timestamps[-1] if timestamps else 'нет времени'}")
    print(f"Пустых ячеек: {sum(missing.values())} | некорректных времён: {bad_times} | повторов времени: {dupes}")
    print(f"Пропусков интервалов >10 мин: {len(gaps)} | отметок не на сетке 10 мин: {off_grid}")
    if gaps:
        print("  Первые пропуски: " + "; ".join(f"{a} → {b} ({mins} мин)" for a, b, mins in gaps[:5]))
    for col, (lo, hi) in extrema.items():
        print(f"  {col}: min={lo:g}, max={hi:g}; пусто={missing[col]}, некорректных чисел={bad_numbers[col]}")
    print(f"Отрицательная мощность: {negative_power} | мощность вне [0,1]: {power_outside}")

    valid_hours = sum(count >= 4 for count in hourly_counts.values())
    full_hours = sum(count == 6 for count in hourly_counts.values())
    print(f"Часовых групп: {len(hourly_counts)} | ≥4 из 6 замеров: {valid_hours} | полных 6/6: {full_hours}")
    return {"times": unique, "hourly": {h for h, n in hourly_counts.items() if n >= 4}, "rows": len(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path, default=DEFAULT_FILES, help="два CSV-файла турбин")
    args = parser.parse_args()
    results = [inspect(path) for path in args.files]
    if len(results) >= 2 and all(results[:2]):
        a, b = results[:2]
        common_ts = a["times"] & b["times"]
        common_hours = a["hourly"] & b["hourly"]
        print("\n## Сравнение двух турбин")
        print(f"Общие 10-минутные отметки: {len(common_ts):,}")
        print(f"Часов с ≥4 замерами у каждой турбины: {len(common_hours):,}")
        print(f"Отметок только у турбины 1: {len(a['times'] - b['times']):,}")
        print(f"Отметок только у турбины 2: {len(b['times'] - a['times']):,}")
        feb_hours = sum(datetime(2026, 2, 1) <= h < datetime(2026, 3, 1) for h in common_hours)
        print(f"Общих пригодных часов в феврале 2026: {feb_hours} (для прогноза фактической мощности не должно быть)")
    print("\nПримечание: критерий ≥4 замеров/час — диагностический. Он не меняет исходные CSV.")


if __name__ == "__main__":
    main()
