"""Append-only audit logger."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditLog

logger = logging.getLogger("unleash.audit")


async def log_action(
    session: AsyncSession,
    username: str,
    action: str,
    user_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
):
    entry = AuditLog(
        timestamp=datetime.now(timezone.utc),
        user_id=user_id,
        username=username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail_json=json.dumps(detail) if detail else None,
        ip_address=ip_address,
    )
    session.add(entry)
    await session.commit()
    logger.info(f"[{username}] {action} {target_type or ''}:{target_id or ''}")
