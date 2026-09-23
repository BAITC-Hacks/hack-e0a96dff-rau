import csv
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

from ..models import ForecastRun, ForecastValue


MODEL_VERSION = "catboost_power_stage1"


def run_from_artifact(run_id: str, horizon_hours: int, turbine_ids: list[str] | None,
                      session_factory, forecast_csv_path: Path):
    with session_factory() as session:
        run = session.get(ForecastRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run.model_version = MODEL_VERSION
        session.commit()
        try:
            if not forecast_csv_path.exists():
                raise FileNotFoundError(f"Forecast artifact not found: {forecast_csv_path}")
            with forecast_csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                source_rows = list(csv.DictReader(f))
            selected = [r for r in source_rows
                        if int(r["horizon_hours"]) <= horizon_hours
                        and (turbine_ids is None or r["turbine_id"] in turbine_ids)]
            if not selected:
                raise ValueError("No forecast rows match the requested turbine IDs and horizon")
            issue_time = datetime.fromisoformat(selected[0]["issue_time"])
            run.issue_time = issue_time
            for row in selected:
                session.add(ForecastValue(
                    run_id=run_id,
                    turbine_id=row["turbine_id"],
                    target_time=datetime.fromisoformat(row["target_time"]),
                    horizon_hours=int(row["horizon_hours"]),
                    power=float(row["forecast_power"]),
                    wind_speed_100m_ms=float(row["wind_speed_100m_ms"]) if row.get("wind_speed_100m_ms") else None,
                    temperature_2m_c=float(row["temperature_2m_c"]) if row.get("temperature_2m_c") else None,
                ))
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
        except Exception as exc:
            session.rollback()
            run = session.get(ForecastRun, run_id)
            if run is not None:
                run.status = "failed"
                run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                run.error_message = str(exc)[:1000]
                session.commit()


def create_run(session, horizon_hours: int) -> ForecastRun:
    run = ForecastRun(id=str(uuid4()), status="queued", horizon_hours=horizon_hours)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def serialize_run(session, run: ForecastRun):
    count = session.scalar(select(func.count(ForecastValue.id)).where(ForecastValue.run_id == run.id)) or 0
    return {"id": run.id, "status": run.status, "horizon_hours": run.horizon_hours,
            "issue_time": run.issue_time, "created_at": run.created_at, "started_at": run.started_at,
            "completed_at": run.completed_at, "error_message": run.error_message,
            "model_version": run.model_version, "result_count": count}
