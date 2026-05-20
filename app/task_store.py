from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AnalysisTask, utc_now


def create_analysis_task(db: Session, task_id: str, task_type: str, params: dict) -> AnalysisTask:
    task = AnalysisTask(
        id=task_id,
        task_type=task_type,
        status="queued",
        params=params,
        created_at=utc_now(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_analysis_task(db: Session, task_id: str) -> Optional[AnalysisTask]:
    return db.get(AnalysisTask, task_id)


def mark_task_running(task_id: str, task_type: str, params: dict) -> None:
    update_task(task_id, task_type, params, status="running", started_at=utc_now())


def mark_task_success(task_id: str, task_type: str, params: dict, result: dict) -> None:
    update_task(task_id, task_type, params, status="success", result=result, error=None, finished_at=utc_now())


def mark_task_failure(task_id: str, task_type: str, params: dict, error: str) -> None:
    update_task(task_id, task_type, params, status="failure", error=error, finished_at=utc_now())


def update_task(task_id: str, task_type: str, params: dict, **fields) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        task = db.get(AnalysisTask, task_id)
        if task is None:
            task = AnalysisTask(id=task_id, task_type=task_type, params=params, created_at=utc_now())
            db.add(task)

        task.task_type = task_type
        task.params = params
        for key, value in fields.items():
            setattr(task, key, value)
        db.commit()
    finally:
        db.close()
