import csv
import io
import math
from datetime import datetime


REQUIRED_COLUMNS = {
    "ID", "Статистическое время", "Средняя скорость ветра(m/s)",
    "Нормализованная активная мощность", "Средняя температура окружающей среды(°C)",
}
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def _parse_time(raw):
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt)
        except (ValueError, AttributeError):
            pass
    return None


def validate_csv_payload(payload: bytes, max_upload_bytes: int):
    errors, warnings = [], []
    if len(payload) > max_upload_bytes:
        return {"valid": False, "rows": 0, "unique_turbines": 0, "first_timestamp": None,
                "last_timestamp": None, "errors": [f"File exceeds {max_upload_bytes} bytes"], "warnings": []}
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = payload.decode("cp1251")
        except UnicodeDecodeError:
            return {"valid": False, "rows": 0, "unique_turbines": 0, "first_timestamp": None,
                    "last_timestamp": None, "errors": ["CSV encoding must be UTF-8 or Windows-1251"], "warnings": []}
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    columns = set(reader.fieldnames or [])
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        return {"valid": False, "rows": 0, "unique_turbines": 0, "first_timestamp": None,
                "last_timestamp": None, "errors": ["Missing required columns: " + ", ".join(missing)], "warnings": []}

    timestamps, turbines, seen = [], set(), set()
    row_count = 0
    for line, row in enumerate(reader, start=2):
        row_count += 1
        if row_count > 250_000:
            errors.append("CSV exceeds the 250,000 row validation limit")
            break
        ts = _parse_time(row.get("Статистическое время"))
        if ts is None:
            errors.append(f"Row {line}: invalid timestamp")
            continue
        turbine = (row.get("ID") or "").strip()
        if not turbine:
            errors.append(f"Row {line}: ID is empty")
        turbines.add(turbine)
        pair = (turbine, ts)
        if pair in seen:
            errors.append(f"Row {line}: duplicate turbine/timestamp {turbine}/{ts.isoformat(sep=' ')}")
        seen.add(pair)
        timestamps.append(ts)
        for column, label in (("Средняя скорость ветра(m/s)", "wind speed"),
                              ("Нормализованная активная мощность", "normalized power"),
                              ("Средняя температура окружающей среды(°C)", "temperature")):
            raw = (row.get(column) or "").strip()
            try:
                value = float(raw.replace(",", "."))
                if not math.isfinite(value):
                    raise ValueError
            except ValueError:
                errors.append(f"Row {line}: invalid {label}")
                continue
            if label == "normalized power" and not 0 <= value <= 1:
                errors.append(f"Row {line}: normalized power must be in [0, 1]")
            if label == "wind speed" and value < 0:
                errors.append(f"Row {line}: wind speed cannot be negative")
    if timestamps and timestamps != sorted(timestamps):
        warnings.append("Rows are not sorted by timestamp; ingestion should sort them")
    return {"valid": not errors, "rows": row_count, "unique_turbines": len(turbines),
            "first_timestamp": min(timestamps) if timestamps else None,
            "last_timestamp": max(timestamps) if timestamps else None,
            "errors": errors[:100], "warnings": warnings}
