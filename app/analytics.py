from datetime import datetime, timezone
from typing import Dict, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import Device, Reading, User
from app.repositories import get_device_by_identifier
from app.schemas import DeviceAnalysis, MetricStats, Period, UserAnalysis, UserDeviceAnalysis


def normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_period(date_from: Optional[datetime], date_to: Optional[datetime]) -> Period:
    normalized_from, normalized_to = normalize_datetime(date_from), normalize_datetime(date_to)
    if normalized_from and normalized_to and normalized_from > normalized_to:
        raise ValueError("date_from must be less than or equal to date_to")
    return Period(date_from=normalized_from, date_to=normalized_to)


def scoped_reading_select(
    *entities,
    device_id: Optional[int] = None,
    user_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
):
    stmt = select(*entities).select_from(Reading)
    if user_id is not None:
        stmt = stmt.join(Device, Device.id == Reading.device_id).where(Device.user_id == user_id)
    if device_id is not None:
        stmt = stmt.where(Reading.device_id == device_id)
    if date_from is not None:
        stmt = stmt.where(Reading.timestamp >= date_from)
    if date_to is not None:
        stmt = stmt.where(Reading.timestamp <= date_to)
    return stmt


def metric_for_axis(
    db: Session,
    axis: str,
    device_id: Optional[int],
    user_id: Optional[int],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> MetricStats:
    column = getattr(Reading, axis)
    expressions = [
        func.min(column),
        func.max(column),
        func.count(column),
        func.sum(column),
        func.percentile_cont(0.5).within_group(column),
    ]

    row = db.execute(
        scoped_reading_select(
            *expressions,
            device_id=device_id,
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
        )
    ).one()

    count = int(row[2] or 0)
    if count == 0:
        return MetricStats()

    return MetricStats(
        min=float(row[0]),
        max=float(row[1]),
        count=count,
        sum=float(row[3] or 0.0),
        median=float(row[4]) if row[4] is not None else None,
    )


def metrics_for_scope(
    db: Session,
    device_id: Optional[int] = None,
    user_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict[str, MetricStats]:
    return {
        axis: metric_for_axis(db, axis, device_id, user_id, date_from, date_to)
        for axis in ("x", "y", "z")
    }


def compute_device_analysis(
    db: Session,
    device_identifier: str,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Optional[DeviceAnalysis]:
    period = validate_period(date_from, date_to)
    device = get_device_by_identifier(db, device_identifier)
    if device is None:
        return None

    return DeviceAnalysis(
        device_identifier=device.external_id,
        period=period,
        metrics=metrics_for_scope(db, device_id=device.id, date_from=period.date_from, date_to=period.date_to),
    )


def compute_user_analysis(
    db: Session,
    user_id: int,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Optional[UserAnalysis]:
    period = validate_period(date_from, date_to)
    user = db.get(User, user_id)
    if user is None:
        return None

    devices = list(db.execute(select(Device).where(Device.user_id == user_id)).scalars().all())
    device_results = [
        UserDeviceAnalysis(
            device_identifier=device.external_id,
            period=period,
            metrics=metrics_for_scope(db, device_id=device.id, date_from=period.date_from, date_to=period.date_to),
        )
        for device in devices
    ]

    return UserAnalysis(
        user_id=user_id,
        period=period,
        aggregate=metrics_for_scope(db, user_id=user_id, date_from=period.date_from, date_to=period.date_to),
        devices=device_results,
    )