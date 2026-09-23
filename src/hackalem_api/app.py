from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging

from .config import Settings, get_settings
from .database import make_engine, make_session_factory
from . import models  # noqa: F401 - register ORM tables for migrations
from .models import ForecastRun, ForecastValue
from .schemas import CsvValidationRead, ForecastRunCreate, ForecastRunRead, ForecastValueRead, HealthRead
from .services.csv_validation import validate_csv_payload
from .services.forecast_runs import create_run, run_from_artifact, serialize_run
from .services.dashboard import dashboard_data, coordinate_forecast, LocationRequest


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.session_factory = session_factory
        app.state.settings = settings
        yield
        engine.dispose()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

    def get_db():
        with session_factory() as session:
            yield session

    @app.get("/health", response_model=HealthRead, tags=["system"])
    def health():
        try:
            with session_factory() as session:
                session.execute(text("SELECT 1"))
            return {"status": "ok", "database": "ok"}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc

    @app.post("/api/v1/data/validate", response_model=CsvValidationRead, tags=["data"])
    async def validate_data(file: UploadFile = File(...)):
        payload = await file.read(settings.max_upload_bytes + 1)
        result = validate_csv_payload(payload, settings.max_upload_bytes)
        return result

    @app.post("/api/v1/forecast-runs", response_model=ForecastRunRead, status_code=202, tags=["forecasts"])
    def submit_forecast(payload: ForecastRunCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
        run = create_run(db, payload.horizon_hours)
        background_tasks.add_task(run_from_artifact, run.id, payload.horizon_hours, payload.turbine_ids,
                                  session_factory, settings.forecast_csv_path)
        return serialize_run(db, run)

    @app.get("/api/v1/forecast-runs", response_model=list[ForecastRunRead], tags=["forecasts"])
    def list_forecast_runs(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
        runs = db.scalars(select(ForecastRun).order_by(ForecastRun.created_at.desc()).limit(limit)).all()
        return [serialize_run(db, run) for run in runs]

    @app.get("/api/v1/forecast-runs/{run_id}", response_model=ForecastRunRead, tags=["forecasts"])
    def get_forecast_run(run_id: str, db: Session = Depends(get_db)):
        run = db.get(ForecastRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="forecast run not found")
        return serialize_run(db, run)

    @app.get("/api/v1/forecast-runs/{run_id}/results", response_model=list[ForecastValueRead], tags=["forecasts"])
    def get_forecast_results(run_id: str, limit: int = Query(500, ge=1, le=5000),
                             offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
        if db.get(ForecastRun, run_id) is None:
            raise HTTPException(status_code=404, detail="forecast run not found")
        query = (select(ForecastValue).where(ForecastValue.run_id == run_id)
                 .order_by(ForecastValue.target_time, ForecastValue.turbine_id).offset(offset).limit(limit))
        return db.scalars(query).all()

    @app.get("/api/v1/dashboard", tags=["dashboard"])
    def get_dashboard():
        try:
            return dashboard_data(settings)
        except (FileNotFoundError, ValueError, KeyError):
            raise HTTPException(503, "Не найдены данные панели. Запустите run_stage1.py.")

    @app.post("/api/v1/locations/forecast", tags=["dashboard"])
    def forecast_location(payload: LocationRequest):
        try:
            return coordinate_forecast(settings, payload)
        except FileNotFoundError:
            raise HTTPException(503, "Модель не найдена. Запустите run_stage1.py.")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except Exception:
            logging.getLogger(__name__).exception("Coordinate forecast failed")
            raise HTTPException(502, "Не удалось получить погоду или выполнить расчёт. Попробуйте ещё раз.")

    frontend = Path(__file__).resolve().parents[2] / "frontend"
    if frontend.exists():
        app.mount("/static", StaticFiles(directory=frontend), name="static")

        @app.get("/", include_in_schema=False)
        def dashboard_page():
            return FileResponse(frontend / "index.html")

    return app


app = create_app()
