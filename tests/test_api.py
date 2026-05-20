import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.engine import make_url


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL API tests", allow_module_level=True)

database_name = make_url(TEST_DATABASE_URL).database or ""
if "test" not in database_name.lower():
    pytest.skip("TEST_DATABASE_URL must point to a dedicated test database", allow_module_level=True)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Device, Reading
from app.task_store import create_analysis_task
from app.tasks import analyze_device_task, celery_app


celery_app.conf.update(task_always_eager=True, task_eager_propagates=False, task_store_eager_result=False, task_ignore_result=True)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def teardown_module():
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


client = TestClient(app)


def test_collect_and_analyze_device_readings():
    response = client.post("/devices/device-1/readings", json={"x": 1.0, "y": 2.0, "z": 3.0})
    assert response.status_code == 201

    response = client.post("/devices/device-1/readings", json={"x": 5.0, "y": 7.0, "z": 9.0})
    assert response.status_code == 201

    response = client.get("/devices/device-1/analysis")
    assert response.status_code == 200
    payload = response.json()
    assert payload["device_identifier"] == "device-1"
    assert payload["metrics"]["x"] == {"min": 1.0, "max": 5.0, "count": 2, "sum": 6.0, "median": 3.0}
    assert payload["metrics"]["y"]["median"] == 4.5
    assert payload["metrics"]["z"]["sum"] == 12.0


def test_user_analysis_returns_aggregate_and_per_device_metrics():
    response = client.post("/users", json={"name": "Alice", "email": "alice@example.com"})
    assert response.status_code == 201
    user_id = response.json()["id"]

    for identifier in ("device-a", "device-b"):
        response = client.post(f"/users/{user_id}/devices", json={"identifier": identifier})
        assert response.status_code == 201

    client.post("/devices/device-a/readings", json={"x": 1.0, "y": 10.0, "z": 100.0})
    client.post("/devices/device-b/readings", json={"x": 3.0, "y": 30.0, "z": 300.0})

    response = client.get(f"/users/{user_id}/analysis")
    assert response.status_code == 200
    payload = response.json()
    assert payload["aggregate"]["x"]["count"] == 2
    assert payload["aggregate"]["x"]["sum"] == 4.0
    assert len(payload["devices"]) == 2


def test_device_analysis_filters_by_period():
    timestamps = [
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 3, tzinfo=timezone.utc),
    ]
    for index, timestamp in enumerate(timestamps, start=1):
        response = client.post(
            "/devices/period-device/readings",
            json={"x": float(index), "y": float(index * 10), "z": float(index * 100), "timestamp": timestamp.isoformat()},
        )
        assert response.status_code == 201

    response = client.get(
        "/devices/period-device/analysis",
        params={
            "date_from": timestamps[1].isoformat(),
            "date_to": timestamps[2].isoformat(),
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["x"]["count"] == 2
    assert payload["metrics"]["x"]["min"] == 2.0
    assert payload["metrics"]["x"]["median"] == 2.5


def test_empty_device_analysis_returns_zero_counts():
    response = client.post("/users", json={"name": "Empty Owner", "email": "empty@example.com"})
    assert response.status_code == 201
    user_id = response.json()["id"]

    response = client.post(f"/users/{user_id}/devices", json={"identifier": "empty-device"})
    assert response.status_code == 201

    response = client.get("/devices/empty-device/analysis")
    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["x"] == {"min": None, "max": None, "count": 0, "sum": 0.0, "median": None}


def test_invalid_period_uses_unified_error_format():
    client.post("/devices/error-device/readings", json={"x": 1.0, "y": 2.0, "z": 3.0})

    response = client.get(
        "/devices/error-device/analysis",
        params={
            "date_from": "2026-01-03T00:00:00+00:00",
            "date_to": "2026-01-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "422"
    assert payload["error"]["message"] == "date_from must be less than or equal to date_to"


def test_invalid_identifier_and_future_timestamp_are_rejected():
    response = client.post("/users", json={"name": "Invalid Owner", "email": "invalid@example.com"})
    user_id = response.json()["id"]

    response = client.post(f"/users/{user_id}/devices", json={"identifier": "bad identifier"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

    future_timestamp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    response = client.post(
        "/devices/future-device/readings",
        json={"x": 1.0, "y": 2.0, "z": 3.0, "timestamp": future_timestamp},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_parallel_reading_collection_creates_single_device():
    def send_reading(index: int):
        return client.post(
            "/devices/race-device/readings",
            json={"x": float(index), "y": float(index), "z": float(index)},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(send_reading, range(20)))

    assert all(response.status_code == 201 for response in responses)

    db = SessionLocal()
    try:
        device_count = db.execute(select(func.count(Device.id)).where(Device.external_id == "race-device")).scalar_one()
        reading_count = (
            db.execute(
                select(func.count(Reading.id))
                .join(Device, Device.id == Reading.device_id)
                .where(Device.external_id == "race-device")
            ).scalar_one()
        )
    finally:
        db.close()

    assert device_count == 1
    assert reading_count == 20


def test_celery_device_task_success_is_persisted():
    client.post("/devices/task-device/readings", json={"x": 2.0, "y": 4.0, "z": 6.0})

    response = client.post("/analytics/devices/task-device", json={"date_from": None, "date_to": None})
    assert response.status_code == 202
    task_id = response.json()["task_id"]

    response = client.get(f"/analytics/tasks/{task_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["result"]["metrics"]["x"]["median"] == 2.0
    assert payload["finished_at"] is not None


def test_celery_device_task_failure_is_persisted():
    task_id = "missing-device-task"
    params = {"device_identifier": "missing-device", "date_from": None, "date_to": None}
    db = SessionLocal()
    try:
        create_analysis_task(db, task_id, "device", params)
    finally:
        db.close()

    analyze_device_task.apply_async(args=["missing-device", None, None], task_id=task_id)

    response = client.get(f"/analytics/tasks/{task_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failure"
    assert payload["error"] == "Device not found"
