"""Deployment orchestration.

Turns a package + a target selection into ``updateModule`` commands published
over MQTT, and tracks per-robot progress through the download.

Status model
------------
DeploymentTarget: pending -> sent -> downloading -> completed | failed
Deployment:       pending -> in_progress -> completed | partial | failed

`sent` and `downloading` are driven by concrete signals (a successful MQTT
publish, and a hit on the UPK file server). Terminal `completed`/`failed`
transitions come from a robot's OTA report — see ``handle_report``.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..broker.server import UnleashBroker
from ..db.models import Deployment, DeploymentTarget, Package, Robot
from .ota_protocol import build_update_envelope

logger = logging.getLogger("unleash.deploy")

ACTIVE_TARGET_STATES = ("pending", "sent", "downloading")
_TERMINAL = ("completed", "failed")


def _mqtt_alias(module_name: str) -> str:
    """Short alias used as MQTT moduleName to avoid download path collision."""
    return module_name[:2]


def parse_serials(value: str | None) -> list[str]:
    """Parse a serial_list target_value (JSON array or comma-separated)."""
    if not value:
        return []
    value = value.strip()
    if value.startswith("["):
        try:
            return [str(s).strip() for s in json.loads(value) if str(s).strip()]
        except Exception:
            pass
    return [s.strip() for s in value.split(",") if s.strip()]


class DeploymentService:
    def __init__(self, broker: UnleashBroker, session_factory, advertise_host: str, upk_port: int):
        self.broker = broker
        self._session_factory = session_factory
        self.advertise_host = advertise_host
        self.upk_port = upk_port

    def _url_for(self, package: Package) -> str:
        filename = Path(package.file_path).name
        return f"http://{self.advertise_host}:{self.upk_port}/{filename}"

    async def resolve_targets(self, session, target_type: str, target_value: str | None) -> list[str]:
        if target_type == "all":
            result = await session.execute(select(Robot.serial))
            return [s for (s,) in result.all()]
        if target_type == "group":
            result = await session.execute(
                select(Robot.serial).where(Robot.group_id == target_value)
            )
            return [s for (s,) in result.all()]
        if target_type == "serial_list":
            return parse_serials(target_value)
        raise ValueError(f"unknown target_type: {target_type!r}")

    async def create(
        self, session, package: Package, target_type: str, target_value: str | None,
        strategy: str, created_by: str,
    ) -> Deployment:
        """Create the deployment and one target row per resolved serial."""
        serials = await self.resolve_targets(session, target_type, target_value)
        deployment = Deployment(
            package_id=package.id,
            strategy=strategy,
            target_type=target_type,
            target_value=target_value,
            status="pending",
            created_by=created_by,
        )
        session.add(deployment)
        await session.flush()  # assign deployment.id
        for serial in serials:
            session.add(DeploymentTarget(
                deployment_id=deployment.id, robot_serial=serial, status="pending",
            ))
        await session.commit()
        await session.refresh(deployment)
        return deployment

    async def dispatch(self, deployment_id: str):
        """Publish the updateModule command to every connected target."""
        async with self._session_factory() as session:
            deployment = (await session.execute(
                select(Deployment).where(Deployment.id == deployment_id)
            )).scalar_one_or_none()
            if deployment is None:
                return
            package = (await session.execute(
                select(Package).where(Package.id == deployment.package_id)
            )).scalar_one()
            targets = (await session.execute(
                select(DeploymentTarget).where(DeploymentTarget.deployment_id == deployment_id)
            )).scalars().all()

            envelope = build_update_envelope(
                module_name=package.module_name,
                version=package.version,
                url=self._url_for(package),
                sign=package.file_hash,
                size=package.file_size,
                mqtt_module_name=_mqtt_alias(package.module_name),
            )

            now = datetime.now(timezone.utc)
            sent_any = False
            for t in targets:
                if t.robot_serial not in self.broker.clients:
                    t.status = "failed"
                    t.error_message = "robot not connected"
                    t.completed_at = now
                    continue
                ok = await self.broker.send_command(t.robot_serial, envelope)
                if ok:
                    t.status = "sent"
                    t.started_at = now
                    sent_any = True
                    robot = (await session.execute(
                        select(Robot).where(Robot.serial == t.robot_serial)
                    )).scalar_one_or_none()
                    if robot:
                        robot.status = "updating"
                else:
                    t.status = "failed"
                    t.error_message = "publish failed"
                    t.completed_at = now

            deployment.status = "in_progress" if sent_any else "failed"
            if not sent_any:
                deployment.completed_at = now
            await session.commit()
            logger.info(
                f"Dispatched deployment {deployment_id}: "
                f"{sum(1 for t in targets if t.status == 'sent')}/{len(targets)} sent"
            )

    async def handle_download(self, filename: str, client_ip: str):
        """Record that a robot fetched the package from the UPK file server."""
        async with self._session_factory() as session:
            package = (await session.execute(
                select(Package).where(Package.file_path.like(f"%{filename}"))
            )).scalars().first()
            if package is None:
                return

            serial = None
            if client_ip:
                robot = (await session.execute(
                    select(Robot).where(Robot.ip_address == client_ip)
                )).scalar_one_or_none()
                if robot:
                    serial = robot.serial

            query = (
                select(DeploymentTarget)
                .join(Deployment, DeploymentTarget.deployment_id == Deployment.id)
                .where(
                    Deployment.package_id == package.id,
                    DeploymentTarget.status.in_(ACTIVE_TARGET_STATES),
                )
            )
            if serial:
                query = query.where(DeploymentTarget.robot_serial == serial)
            targets = (await session.execute(query)).scalars().all()
            for t in targets:
                t.status = "downloading"
                t.download_count += 1
            await session.commit()

    async def handle_report(self, serial: str, topic: str, payload: bytes):
        """Ingest a ``reportVersion`` MQTT message published by the robot.

        After an OTA install (and periodically as a heartbeat) the robot sends:

            {
                "cmd": "reportVersion",
                "msgId": "<id>",
                "modules": [
                    {"moduleName": "system_patch", "version": "1.0.0", "code": 0},
                    ...
                ]
            }

        code 0 = success; non-zero = failure for that module.

        We match each entry against active DeploymentTargets for this serial
        by (module_name, version).  A heartbeat that doesn't mention any of
        our in-flight modules is silently ignored.
        """
        try:
            data = json.loads(payload)
        except Exception:
            return
        if not isinstance(data, dict) or data.get("cmd") != "reportVersion":
            return

        modules_raw = data.get("modules")
        if not isinstance(modules_raw, list) or not modules_raw:
            return

        # Build a lookup: module_name -> (version, code)
        reported: dict[str, tuple[str, int]] = {}
        for entry in modules_raw:
            if not isinstance(entry, dict):
                continue
            name = entry.get("moduleName") or entry.get("name")
            version = entry.get("version")
            raw_code = entry.get("code", -1)
            if not (name and version is not None):
                continue
            try:
                code = int(raw_code)
            except (TypeError, ValueError):
                code = -1
            reported[name] = (str(version), code)

        if not reported:
            return

        async with self._session_factory() as session:
            # Load all active targets for this serial together with their Package
            # in one query to avoid N+1 lookups.
            rows = (await session.execute(
                select(DeploymentTarget, Package)
                .join(Deployment, DeploymentTarget.deployment_id == Deployment.id)
                .join(Package, Deployment.package_id == Package.id)
                .where(
                    DeploymentTarget.robot_serial == serial,
                    DeploymentTarget.status.in_(ACTIVE_TARGET_STATES),
                )
            )).all()

            if not rows:
                return

            now = datetime.now(timezone.utc)
            affected: set[str] = set()

            for target, package in rows:
                alias = _mqtt_alias(package.module_name)
                if package.module_name in reported:
                    rep_version, rep_code = reported[package.module_name]
                elif alias in reported:
                    rep_version, rep_code = reported[alias]
                else:
                    continue
                if rep_version != package.version:
                    continue  # wrong version — different deployment or downgrade

                success = rep_code == 0
                target.status = "completed" if success else "failed"
                target.completed_at = now
                if not success:
                    target.error_message = f"robot reported code {rep_code}"

                robot = (await session.execute(
                    select(Robot).where(Robot.serial == serial)
                )).scalar_one_or_none()
                if robot:
                    robot.status = "online" if success else "error"

                affected.add(target.deployment_id)

            for dep_id in affected:
                await self._recompute(session, dep_id, now)

            if affected:
                await session.commit()

    async def _recompute(self, session, deployment_id: str, now: datetime):
        deployment = (await session.execute(
            select(Deployment).where(Deployment.id == deployment_id)
        )).scalar_one_or_none()
        if deployment is None:
            return
        targets = (await session.execute(
            select(DeploymentTarget).where(DeploymentTarget.deployment_id == deployment_id)
        )).scalars().all()
        if not all(t.status in _TERMINAL for t in targets):
            return
        completed = sum(1 for t in targets if t.status == "completed")
        if completed == len(targets):
            deployment.status = "completed"
        elif completed == 0:
            deployment.status = "failed"
        else:
            deployment.status = "partial"
        deployment.completed_at = now
