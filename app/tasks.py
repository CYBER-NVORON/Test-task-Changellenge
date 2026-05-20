from datetime import datetime
from typing import Optional

from celery import Celery

from app.analytics import compute_device_analysis, compute_user_analysis
from app.config import settings
from app.database import SessionLocal
from app.task_store import mark_task_failure, mark_task_running, mark_task_success


celery_app = Celery(
    "device_statistics",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    accept_content=["json"],
    result_serializer="json",
    task_serializer="json",
    timezone="UTC",
)


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value)


@celery_app.task(bind=True, name="analytics.device")
def analyze_device_task(
    self,
    device_identifier: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    task_id = self.request.id
    params = {"device_identifier": device_identifier, "date_from": date_from, "date_to": date_to}
    mark_task_running(task_id, "device", params)
    db = SessionLocal()
    try:
        result = compute_device_analysis(db, device_identifier, parse_datetime(date_from), parse_datetime(date_to))
        if result is None:
            raise ValueError("Device not found")
        payload = result.model_dump(mode="json")
        mark_task_success(task_id, "device", params, payload)
        return payload
    except Exception as exc:
        mark_task_failure(task_id, "device", params, str(exc))
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="analytics.user")
def analyze_user_task(self, user_id: int, date_from: Optional[str] = None, date_to: Optional[str] = None) -> dict:
    task_id = self.request.id
    params = {"user_id": user_id, "date_from": date_from, "date_to": date_to}
    mark_task_running(task_id, "user", params)
    db = SessionLocal()
    try:
        result = compute_user_analysis(db, user_id, parse_datetime(date_from), parse_datetime(date_to))
        if result is None:
            raise ValueError("User not found")
        payload = result.model_dump(mode="json")
        mark_task_success(task_id, "user", params, payload)
        return payload
    except Exception as exc:
        mark_task_failure(task_id, "user", params, str(exc))
        raise
    finally:
        db.close()
