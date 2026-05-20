from typing import Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import Device


def get_device_by_identifier(db: Session, identifier: str) -> Optional[Device]:
    return db.execute(select(Device).where(Device.external_id == identifier)).scalar_one_or_none()


def get_or_create_device(db: Session, identifier: str) -> Device:
    device = get_device_by_identifier(db, identifier)
    if device is not None:
        return device

    device = Device(external_id=identifier)
    db.add(device)
    try:
        db.flush()
        return device
    except IntegrityError:
        db.rollback()
        existing = get_device_by_identifier(db, identifier)
        if existing is None:
            raise
        return existing