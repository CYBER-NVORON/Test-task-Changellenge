from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional
from uuid import uuid4
from fastapi import Body, Depends, FastAPI, HTTPException, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.analytics import compute_device_analysis, compute_user_analysis, normalize_datetime, validate_period
from app.config import settings
from app.database import get_db, init_db
from app.models import AnalysisTask, Device, Reading, User, utc_now
from app.repositories import get_device_by_identifier, get_or_create_device
from app.schemas import (
    DEVICE_IDENTIFIER_PATTERN,
    DeviceAnalysis,
    DeviceCreate,
    DeviceOut,
    Period,
    ReadingOut,
    StatisticIn,
    TaskCreated,
    TaskStatus,
    UserAnalysis,
    UserCreate,
    UserOut,
)
from app.task_store import create_analysis_task, get_analysis_task, mark_task_failure
from app.tasks import analyze_device_task, analyze_user_task


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


def error_content(code: str, message: str, details=None) -> dict:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    details = None
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or "HTTP error")
        details = detail.get("details")
    elif isinstance(detail, list):
        message = "HTTP error"
        details = detail
    else:
        message = str(detail)

    return JSONResponse(
        status_code=exc.status_code,
        content=error_content(str(exc.status_code), message, jsonable_encoder(details)),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_content(
            "validation_error",
            "Request validation failed",
            jsonable_encoder(exc.errors()),
        ),
    )


def device_to_schema(device: Device) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        identifier=device.external_id,
        user_id=device.user_id,
        created_at=device.created_at,
    )


def iso_or_none(value: Optional[datetime]) -> Optional[str]:
    return normalize_datetime(value).isoformat() if value else None


def task_response(request: Request, task_id: str) -> TaskCreated:
    return TaskCreated(
        task_id=task_id,
        status="queued",
        status_url=str(request.url_for("get_task_status", task_id=task_id)),
    )


def task_to_schema(task: AnalysisTask) -> TaskStatus:
    return TaskStatus(
        task_id=task.id,
        status=task.status,
        task_type=task.task_type,
        params=task.params,
        result=task.result,
        error=task.error,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


def enqueue_task_or_fail(task, task_id: str, args: list, task_type: str, params: dict) -> None:
    try:
        task.apply_async(args=args, task_id=task_id)
    except Exception as exc:
        mark_task_failure(task_id, task_type, params, str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue analytics task",
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    user = User(name=payload.name, email=payload.email)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User email already exists")
    db.refresh(user)
    return user


@app.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@app.post("/users/{user_id}/devices", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
def add_user_device(user_id: int, payload: DeviceCreate, db: Session = Depends(get_db)) -> DeviceOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    device = get_or_create_device(db, payload.identifier)
    if device.user_id not in (None, user_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device is already assigned to another user")

    device.user_id = user_id

    db.commit()
    db.refresh(device)
    return device_to_schema(device)


@app.get("/users/{user_id}/devices", response_model=List[DeviceOut])
def list_user_devices(user_id: int, db: Session = Depends(get_db)) -> List[DeviceOut]:
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    devices = db.execute(select(Device).where(Device.user_id == user_id)).scalars().all()
    return [device_to_schema(device) for device in devices]


@app.post("/devices/{device_identifier}/readings", response_model=ReadingOut, status_code=status.HTTP_201_CREATED)
def collect_reading(
    device_identifier: str = Path(..., min_length=1, max_length=100, pattern=DEVICE_IDENTIFIER_PATTERN),
    payload: StatisticIn = Body(...),
    db: Session = Depends(get_db),
) -> ReadingOut:
    device = get_or_create_device(db, device_identifier)
    reading = Reading(
        device_id=device.id,
        timestamp=normalize_datetime(payload.timestamp) or utc_now(),
        x=payload.x,
        y=payload.y,
        z=payload.z,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return ReadingOut(
        id=reading.id,
        device_identifier=device.external_id,
        timestamp=reading.timestamp,
        x=reading.x,
        y=reading.y,
        z=reading.z,
    )


@app.get("/devices/{device_identifier}/analysis", response_model=DeviceAnalysis)
def get_device_analysis(
    device_identifier: str = Path(..., min_length=1, max_length=100, pattern=DEVICE_IDENTIFIER_PATTERN),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
) -> DeviceAnalysis:
    try:
        result = compute_device_analysis(db, device_identifier, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return result


@app.get("/users/{user_id}/analysis", response_model=UserAnalysis)
def get_user_analysis(
    user_id: int,
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
) -> UserAnalysis:
    try:
        result = compute_user_analysis(db, user_id, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return result


@app.post("/analytics/devices/{device_identifier}", response_model=TaskCreated, status_code=status.HTTP_202_ACCEPTED)
def queue_device_analysis(
    request: Request,
    payload: Period,
    device_identifier: str = Path(..., min_length=1, max_length=100, pattern=DEVICE_IDENTIFIER_PATTERN),
    db: Session = Depends(get_db),
) -> TaskCreated:
    try:
        validate_period(payload.date_from, payload.date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if get_device_by_identifier(db, device_identifier) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    task_id = str(uuid4())
    params = {
        "device_identifier": device_identifier,
        "date_from": iso_or_none(payload.date_from),
        "date_to": iso_or_none(payload.date_to),
    }
    create_analysis_task(db, task_id, "device", params)
    enqueue_task_or_fail(
        analyze_device_task,
        task_id,
        [device_identifier, params["date_from"], params["date_to"]],
        "device",
        params,
    )
    return task_response(request, task_id)


@app.post("/analytics/users/{user_id}", response_model=TaskCreated, status_code=status.HTTP_202_ACCEPTED)
def queue_user_analysis(
    user_id: int,
    request: Request,
    payload: Period,
    db: Session = Depends(get_db),
) -> TaskCreated:
    try:
        validate_period(payload.date_from, payload.date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if db.get(User, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    task_id = str(uuid4())
    params = {"user_id": user_id, "date_from": iso_or_none(payload.date_from), "date_to": iso_or_none(payload.date_to)}
    create_analysis_task(db, task_id, "user", params)
    enqueue_task_or_fail(analyze_user_task, task_id, [user_id, params["date_from"], params["date_to"]], "user", params)
    return task_response(request, task_id)


@app.get("/analytics/tasks/{task_id}", response_model=TaskStatus, name="get_task_status")
def get_task_status(task_id: str, db: Session = Depends(get_db)) -> TaskStatus:
    task = get_analysis_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analytics task not found")
    return task_to_schema(task)