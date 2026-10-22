"""Audit log API routes."""

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import CurrentUser, require_role
from ..db.engine import get_session
from ..db.models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryOut(BaseModel):
    id: int
    timestamp: datetime
    user_id: str | None
    username: str
    action: str
    target_type: str | None
    target_id: str | None
    detail_json: str | None
    ip_address: str | None

    model_config = {"from_attributes": True}


class AuditPage(BaseModel):
    items: list[AuditEntryOut]
    total: int
    page: int
    page_size: int


@router.get("/logs", response_model=AuditPage)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: str | None = None,
    username: str | None = None,
    target_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    _: CurrentUser = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_session),
):
    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    if username:
        query = query.where(AuditLog.username == username)
        count_query = count_query.where(AuditLog.username == username)
    if target_id:
        query = query.where(AuditLog.target_id == target_id)
        count_query = count_query.where(AuditLog.target_id == target_id)
    if from_date:
        query = query.where(AuditLog.timestamp >= from_date)
        count_query = count_query.where(AuditLog.timestamp >= from_date)
    if to_date:
        query = query.where(AuditLog.timestamp <= to_date)
        count_query = count_query.where(AuditLog.timestamp <= to_date)

    total = (await session.execute(count_query)).scalar() or 0

    query = query.order_by(AuditLog.timestamp.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)

    return AuditPage(
        items=result.scalars().all(),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/export")
async def export_audit_logs(
    format: str = Query("csv", pattern="^(csv|json)$"),
    _: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()))
    rows = result.scalars().all()

    if format == "json":
        data = [
            {
                "timestamp": r.timestamp.isoformat(),
                "username": r.username,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": json.loads(r.detail_json) if r.detail_json else None,
                "ip_address": r.ip_address,
            }
            for r in rows
        ]
        return StreamingResponse(
            io.BytesIO(json.dumps(data, indent=2).encode()),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audit_log.json"},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "username", "action", "target_type", "target_id", "detail", "ip_address"])
    for r in rows:
        writer.writerow([
            r.timestamp.isoformat(), r.username, r.action,
            r.target_type, r.target_id, r.detail_json, r.ip_address,
        ])
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )
