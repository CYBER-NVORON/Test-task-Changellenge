from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas import DeviceCreate, StatisticIn


def test_device_identifier_validation_accepts_safe_identifiers():
    payload = DeviceCreate(identifier="device-001.alpha")

    assert payload.identifier == "device-001.alpha"


def test_device_identifier_validation_rejects_spaces():
    with pytest.raises(ValidationError):
        DeviceCreate(identifier="bad identifier")


def test_statistic_validation_rejects_far_future_timestamp():
    with pytest.raises(ValidationError):
        StatisticIn(
            x=1.0,
            y=2.0,
            z=3.0,
            timestamp=datetime.now(timezone.utc) + timedelta(days=1),
        )
