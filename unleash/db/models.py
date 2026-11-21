"""SQLAlchemy ORM models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="operator")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RobotGroup(Base):
    __tablename__ = "robot_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))

    robots: Mapped[list["Robot"]] = relationship(back_populates="group")


class Robot(Base):
    __tablename__ = "robots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    serial: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    model: Mapped[str | None] = mapped_column(String(32))
    nickname: Mapped[str | None] = mapped_column(String(128))
    firmware_version: Mapped[str | None] = mapped_column(String(32))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    mqtt_client_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="offline")
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    group_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("robot_groups.id"))
    metadata_json: Mapped[str | None] = mapped_column(Text)

    group: Mapped[RobotGroup | None] = relationship(back_populates="robots")


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    module_name: Mapped[str] = mapped_column(String(64), nullable=False)
    commands_json: Mapped[str] = mapped_column(Text, nullable=False)
    extra_files_json: Mapped[str | None] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_package_name_version", "name", "version", unique=True),)


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    package_id: Mapped[str] = mapped_column(String(36), ForeignKey("packages.id"), nullable=False)
    strategy: Mapped[str] = mapped_column(String(16), default="immediate")
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_value: Mapped[str | None] = mapped_column(Text)
    stage_percent: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    package: Mapped[Package] = relationship()
    targets: Mapped[list["DeploymentTarget"]] = relationship(back_populates="deployment")


class DeploymentTarget(Base):
    __tablename__ = "deployment_targets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deployment_id: Mapped[str] = mapped_column(String(36), ForeignKey("deployments.id"), nullable=False)
    robot_serial: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    download_count: Mapped[int] = mapped_column(Integer, default=0)

    deployment: Mapped[Deployment] = relationship(back_populates="targets")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    detail_json: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(45))

    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_user", "user_id"),
        Index("ix_audit_action", "action"),
    )


class BrokerEventLog(Base):
    __tablename__ = "broker_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    robot_serial: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_broker_event_serial", "robot_serial"),
        Index("ix_broker_event_ts", "timestamp"),
    )
