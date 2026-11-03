"""FastAPI application factory."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import bcrypt as _bcrypt
from sqlalchemy import select

from .api import (
    audit_routes,
    auth_routes,
    command_routes,
    deployment_routes,
    enroll_routes,
    fleet_routes,
    package_routes,
    system_routes,
    websocket_routes,
)
from .api.websocket_routes import setup_broker_ws_hooks
from .broker.server import UnleashBroker
from .config import settings
from .db.engine import async_session, engine
from .db.models import Base, User
from .fleet.manager import FleetManager
from .packages.deployment import DeploymentService
from .packages.examples import seed_example_packages
from .packages.file_server import UPKFileServer

logger = logging.getLogger("unleash")

broker: UnleashBroker | None = None
fleet_manager: FleetManager | None = None
upk_server: UPKFileServer | None = None
deployment_service: DeploymentService | None = None


async def _ensure_admin_user():
    async with async_session() as session:
        result = await session.execute(select(User).where(User.role == "admin"))
        if result.scalar_one_or_none():
            return
        generated_pw = secrets.token_urlsafe(16)
        admin = User(
            username="admin",
            password_hash=_bcrypt.hashpw(generated_pw.encode(), _bcrypt.gensalt()).decode(),
            role="admin",
            email="admin@localhost",
        )
        session.add(admin)
        await session.commit()
        pw_file = settings.data_dir / "admin_password"
        pw_file.write_text(generated_pw)
        try:
            pw_file.chmod(0o600)
        except OSError:
            pass
        logger.warning(
            "Created admin user — initial password written to %s", pw_file
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global broker, fleet_manager, upk_server, deployment_service

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_admin_user()

    async with async_session() as session:
        await seed_example_packages(session, settings.package_dir)

    cert_path = Path(settings.mqtt_cert_path) if settings.mqtt_cert_path else None
    key_path = Path(settings.mqtt_key_path) if settings.mqtt_key_path else None

    broker = UnleashBroker(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        cert_path=cert_path,
        key_path=key_path,
        require_auth=settings.mqtt_require_auth,
        use_tls=settings.mqtt_use_tls,
    )

    fleet_manager = FleetManager(broker)
    fleet_manager.set_session_factory(async_session)
    fleet_manager.setup_broker_hooks()

    setup_broker_ws_hooks(broker)
    command_routes.set_broker(broker)
    system_routes.set_broker(broker)

    deployment_service = DeploymentService(
        broker,
        async_session,
        advertise_host=settings.upk_advertise_host,
        upk_port=settings.upk_server_port,
    )
    deployment_routes.set_service(deployment_service)

    # Robot OTA reports arrive as ordinary MQTT publishes; feed them in.
    def _on_robot_message(serial, topic, payload):
        asyncio.ensure_future(deployment_service.handle_report(serial, topic, payload))

    broker.on_message(_on_robot_message)

    upk_server = UPKFileServer(
        package_dir=settings.package_dir,
        host=settings.upk_server_host,
        port=settings.upk_server_port,
        on_download=deployment_service.handle_download,
    )

    await broker.start()
    await upk_server.start()
    logger.info("UnLeash started")

    yield

    await upk_server.stop()
    await broker.stop()
    await engine.dispose()
    logger.info("UnLeash stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="UnLeash",
        description="Own your Unitree robot — enrollment, fleet management, and OTA deployment",
        version="2.0.0a1",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_routes.router, prefix="/api/v1")
    app.include_router(fleet_routes.router, prefix="/api/v1")
    app.include_router(command_routes.router, prefix="/api/v1")
    app.include_router(package_routes.router, prefix="/api/v1")
    app.include_router(deployment_routes.router, prefix="/api/v1")
    app.include_router(audit_routes.router, prefix="/api/v1")
    app.include_router(system_routes.router, prefix="/api/v1")
    app.include_router(enroll_routes.router, prefix="/api/v1")
    app.include_router(websocket_routes.router)
    app.include_router(enroll_routes.ws_router)

    frontend_dist = Path(__file__).parent / "frontend_dist"
    if not frontend_dist.exists():
        frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app
