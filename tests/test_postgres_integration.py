import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


POSTGRES_URL = os.getenv("TEST_DATABASE_URL")

if not POSTGRES_URL:
    pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests", allow_module_level=True)

database_name = make_url(POSTGRES_URL).database or ""
if "test" not in database_name.lower():
    pytest.skip("TEST_DATABASE_URL must point to a dedicated test database", allow_module_level=True)

os.environ["DATABASE_URL"] = POSTGRES_URL

from app.analytics import compute_device_analysis
from app.database import Base
from app.models import Device, Reading


def test_postgres_device_analysis_uses_database_aggregates():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        device = Device(external_id="pg-device")
        db.add(device)
        db.flush()
        for value in (1.0, 4.0, 10.0, 20.0):
            db.add(
                Reading(
                    device_id=device.id,
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    x=value,
                    y=value * 10,
                    z=value * 100,
                )
            )
        db.commit()

        result = compute_device_analysis(db, "pg-device")

        assert result is not None
        assert result.metrics["x"].count == 4
        assert result.metrics["x"].sum == 35.0
        assert result.metrics["x"].median == 7.0
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
