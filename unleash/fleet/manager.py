"""Fleet manager: bridges MQTT broker state and the database."""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..broker.server import UnleashBroker, MQTTClient
from ..db.models import Robot, RobotGroup

logger = logging.getLogger("unleash.fleet")


class FleetManager:
    def __init__(self, broker: UnleashBroker):
        self.broker = broker
        self._session_factory = None

    def set_session_factory(self, factory):
        self._session_factory = factory

    def setup_broker_hooks(self):
        self.broker.on_connect(self._on_robot_connect)
        self.broker.on_disconnect(self._on_robot_disconnect)

    def _on_robot_connect(self, serial: str, client: MQTTClient):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._handle_connect(serial, client))
        except RuntimeError:
            pass

    def _on_robot_disconnect(self, serial: str):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._handle_disconnect(serial))
        except RuntimeError:
            pass

    async def _handle_connect(self, serial: str, client: MQTTClient):
        if not self._session_factory:
            return
        async with self._session_factory() as session:
            result = await session.execute(select(Robot).where(Robot.serial == serial))
            robot = result.scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if robot:
                robot.status = "online"
                robot.last_seen = now
                robot.ip_address = client.ip_address
                robot.mqtt_client_id = client.client_id
            else:
                robot = Robot(
                    serial=serial,
                    status="online",
                    last_seen=now,
                    first_seen=now,
                    ip_address=client.ip_address,
                    mqtt_client_id=client.client_id,
                )
                session.add(robot)
            await session.commit()
            logger.info(f"Fleet: {serial} online")

    async def _handle_disconnect(self, serial: str):
        if not self._session_factory:
            return
        async with self._session_factory() as session:
            result = await session.execute(select(Robot).where(Robot.serial == serial))
            robot = result.scalar_one_or_none()
            if robot:
                robot.status = "offline"
                robot.last_seen = datetime.now(timezone.utc)
                await session.commit()
            logger.info(f"Fleet: {serial} offline")

    async def get_fleet_status(self, session: AsyncSession) -> dict:
        result = await session.execute(
            select(Robot.status, func.count(Robot.id)).group_by(Robot.status)
        )
        counts = dict(result.all())
        return {
            "total": sum(counts.values()),
            "online": counts.get("online", 0),
            "offline": counts.get("offline", 0),
            "updating": counts.get("updating", 0),
            "error": counts.get("error", 0),
        }
