from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


DEVICE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: Optional[EmailStr] = None


class UserOut(BaseModel):
    id: int
    name: str
    email: Optional[EmailStr] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeviceCreate(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=100, pattern=DEVICE_IDENTIFIER_PATTERN)


class DeviceOut(BaseModel):
    id: int
    identifier: str
    user_id: Optional[int] = None
    created_at: datetime


class StatisticIn(BaseModel):
    x: float = Field(..., allow_inf_nan=False)
    y: float = Field(..., allow_inf_nan=False)
    z: float = Field(..., allow_inf_nan=False)
    timestamp: Optional[datetime] = None

    @field_validator("timestamp")
    @classmethod
    def reject_far_future_timestamp(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return value
        if value.tzinfo is None:
            normalized = value.replace(tzinfo=timezone.utc)
        else:
            normalized = value.astimezone(timezone.utc)
        if normalized > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("timestamp must not be more than 5 minutes in the future")
        return value


class ReadingOut(BaseModel):
    id: int
    device_identifier: str
    timestamp: datetime
    x: float
    y: float
    z: float


class Period(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class MetricStats(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    count: int = 0
    sum: float = 0.0
    median: Optional[float] = None


class DeviceAnalysis(BaseModel):
    device_identifier: str
    period: Period
    metrics: Dict[str, MetricStats]


class UserDeviceAnalysis(DeviceAnalysis):
    pass


class UserAnalysis(BaseModel):
    user_id: int
    period: Period
    aggregate: Dict[str, MetricStats]
    devices: List[UserDeviceAnalysis]


class TaskCreated(BaseModel):
    task_id: str
    status: str
    status_url: str


class TaskStatus(BaseModel):
    task_id: str
    status: str
    task_type: Optional[str] = None
    params: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
