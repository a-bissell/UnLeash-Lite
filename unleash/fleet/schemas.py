"""Pydantic schemas for fleet API requests and responses."""

from datetime import datetime
from pydantic import BaseModel


class RobotOut(BaseModel):
    id: str
    serial: str
    model: str | None = None
    nickname: str | None = None
    firmware_version: str | None = None
    ip_address: str | None = None
    status: str
    last_seen: datetime | None = None
    first_seen: datetime
    group_id: str | None = None
    group_name: str | None = None

    model_config = {"from_attributes": True}


class RobotUpdate(BaseModel):
    nickname: str | None = None
    model: str | None = None
    group_id: str | None = None


class RobotGroupOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    created_at: datetime
    robot_count: int = 0

    model_config = {"from_attributes": True}


class RobotGroupCreate(BaseModel):
    name: str
    description: str | None = None


class FleetStatus(BaseModel):
    total: int
    online: int
    offline: int
    updating: int
    error: int
