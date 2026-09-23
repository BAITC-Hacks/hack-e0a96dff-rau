#!/usr/bin/env python3
"""Aggregate the two HackAlem 10-minute turbine CSVs into hourly rows."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_DIR = Path.home() / "Downloads"
DEFAULT_FILES = [
    DEFAULT_DIR / "Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine 1.csv",
    DEFAULT_DIR / "Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine 2.csv",
]
TIME_COL = "Статистическое время"
VALUE_COLS = {
    "wind_ms": "Средняя скорость ветра(m/s)",
    "power": "Нормализованная активная мощность",
    "temp_c": "Средняя температура окружающей среды(°C)",
}


def read_rows(path: Path):
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                sample = f.read(8192)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                except csv.Error:
                    dialect = csv.excel
                return list(csv.DictReader(f, dialect=dialect))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Не удалось прочитать кодировку файла: {path}")


def parse_time(raw: str):
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path, default=DEFAULT_FILES)
    parser.add_argument("--min-samples", type=int, default=4,
                        help="минимум 10-минутных замеров в час (по умолчанию 4 из 6)")
    parser.add_argument("--output", type=Path, default=Path("outputs/hourly_power.csv"))
    args = parser.parse_args()
    if args.min_samples < 1 or args.min_samples > 6:
        parser.error("--min-samples должен быть от 1 до 6")

    output_rows = []
    totals = []
    for turbine_id, path in enumerate(args.files, start=1):
        if not path.exists():
            parser.error(f"Файл не найден: {path}")
        groups = defaultdict(lambda: {key: [] for key in VALUE_COLS})
        invalid = 0
        for row in read_rows(path):
            ts = parse_time(row.get(TIME_COL, ""))
            if ts is None:
                invalid += 1
                continue
            hour = ts.replace(minute=0, second=0, microsecond=0)
            for key, source_col in VALUE_COLS.items():
                raw = (row.get(source_col) or "").strip()
                if not raw:
                    continue
                try:
                    groups[hour][key].append(float(raw.replace(",", ".")))
                except ValueError:
                    continue

        accepted = 0
        rejected = 0
        for hour, values in sorted(groups.items()):
            # Require the minimum measurement count for each model input and target.
            if any(len(values[key]) < args.min_samples for key in VALUE_COLS):
                rejected += 1
                continue
            output_rows.append({
                "timestamp": hour.strftime("%Y-%m-%d %H:%M:%S"),
                "turbine_id": turbine_id,
                "wind_ms": sum(values["wind_ms"]) / len(values["wind_ms"]),
                "power": sum(values["power"]) / len(values["power"]),
                "temp_c": sum(values["temp_c"]) / len(values["temp_c"]),
                "n_samples": min(len(values[key]) for key in VALUE_COLS),
            })
            accepted += 1
        totals.append((path.name, accepted, rejected, invalid))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "turbine_id", "wind_ms", "power", "temp_c", "n_samples"])
        writer.writeheader()
        for row in sorted(output_rows, key=lambda r: (r["timestamp"], r["turbine_id"])):
            writer.writerow({**row, "wind_ms": f'{row["wind_ms"]:.5f}', "power": f'{row["power"]:.6f}', "temp_c": f'{row["temp_c"]:.4f}'})

    print(f"Создан файл: {args.output.resolve()}")
    print(f"Строк после агрегации: {len(output_rows):,}")
    print(f"Условие: минимум {args.min_samples} из 6 замеров для каждого показателя")
    for name, accepted, rejected, invalid in totals:
        print(f"{name}: пригодных часов={accepted:,}, отброшено часов={rejected:,}, некорректных времён={invalid}")
    print("Время оставлено как в CSV; часовой пояс пока не преобразовывался.")


if __name__ == "__main__":
    main()
