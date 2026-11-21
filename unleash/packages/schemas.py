"""Pydantic schemas for package management."""

from datetime import datetime
from pydantic import BaseModel


class CommandEntry(BaseModel):
    Cmd: str
    Delay: float = 0.0
    ExpectCode: list[int] = [0]
    IgnoreUnexpected: bool = True


class PackageCreate(BaseModel):
    name: str
    version: str
    description: str | None = None
    module_name: str = "system_patch"
    commands: list[CommandEntry]


class PackageOut(BaseModel):
    id: str
    name: str
    version: str
    description: str | None
    module_name: str
    commands_json: str
    file_hash: str
    file_size: int
    created_at: datetime
    created_by: str | None
    is_archived: bool

    model_config = {"from_attributes": True}


class PackageTemplateOut(BaseModel):
    """A built-in example used as a starting point in the Package Builder."""
    name: str
    version: str
    module_name: str
    description: str
    commands: list[CommandEntry]


class DeploymentCreate(BaseModel):
    package_id: str
    target_type: str  # "all", "group", "serial_list"
    target_value: str | None = None
    strategy: str = "immediate"


class DeploymentOut(BaseModel):
    id: str
    package_id: str
    strategy: str
    target_type: str
    target_value: str | None
    status: str
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class DeploymentTargetOut(BaseModel):
    robot_serial: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    download_count: int

    model_config = {"from_attributes": True}


class DeploymentDetailOut(DeploymentOut):
    targets: list[DeploymentTargetOut]
