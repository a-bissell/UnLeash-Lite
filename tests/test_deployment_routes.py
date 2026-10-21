"""HTTP-level tests for the deployment routes: auth, dispatch, serialization.

Exercises the real request path (RBAC, the service, the detail response)
with the DB dependency overridden to a throwaway SQLite engine and a fake
broker. The app lifespan is not entered, so no real broker/file server binds.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from unleash.api import deployment_routes
from unleash.app import create_app
from unleash.auth.jwt_handler import create_access_token
from unleash.db.engine import get_session
from unleash.db.models import Base, Package, Robot
from unleash.packages.deployment import DeploymentService


class FakeBroker:
    def __init__(self, connected):
        self.clients = {s: object() for s in connected}

    async def send_command(self, serial, payload):
        return True


@pytest.fixture
def env(tmp_path):
    # NullPool: the fixture seeds in one event loop and TestClient runs the
    # app in another; pooled aiosqlite connections are loop-bound, so we must
    # not reuse them across loops.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}", poolclass=NullPool
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import asyncio

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as s:
            s.add(Robot(serial="R1", status="online", ip_address="10.0.0.5"))
            s.add(Package(
                name="patch", version="1.0.0", module_name="system_patch",
                commands_json="[]", file_hash="h", file_size=9,
                file_path=str(tmp_path / "patch_1.0.0.upk"),
            ))
            await s.commit()
            return (await s.execute(select(Package.id))).scalar_one()

    pkg_id = asyncio.run(setup())

    app = create_app()

    async def override_get_session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    deployment_routes.set_service(
        DeploymentService(FakeBroker({"R1"}), factory, "10.0.0.1", 8899)
    )

    yield TestClient(app), pkg_id

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _auth(role):
    return {"Authorization": f"Bearer {create_access_token('u', 'tester', role)}"}


def test_create_deployment_dispatches(env):
    client, pkg_id = env
    resp = client.post(
        "/api/v1/deployments",
        json={"package_id": pkg_id, "target_type": "serial_list", "target_value": "R1"},
        headers=_auth("operator"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "in_progress"
    assert len(body["targets"]) == 1
    assert body["targets"][0] == {
        "robot_serial": "R1", "status": "sent", "download_count": 0,
        "started_at": body["targets"][0]["started_at"], "completed_at": None,
        "error_message": None,
    }

    # Listed and retrievable.
    assert any(d["id"] == body["id"] for d in client.get("/api/v1/deployments", headers=_auth("viewer")).json())
    assert client.get(f"/api/v1/deployments/{body['id']}", headers=_auth("viewer")).json()["id"] == body["id"]


def test_viewer_cannot_deploy(env):
    client, pkg_id = env
    resp = client.post(
        "/api/v1/deployments",
        json={"package_id": pkg_id, "target_type": "serial_list", "target_value": "R1"},
        headers=_auth("viewer"),
    )
    assert resp.status_code == 403


def test_unknown_package_404(env):
    client, _ = env
    resp = client.post(
        "/api/v1/deployments",
        json={"package_id": "does-not-exist", "target_type": "all"},
        headers=_auth("operator"),
    )
    assert resp.status_code == 404


def test_no_matching_targets_400(env):
    client, pkg_id = env
    # A group with no members resolves to zero targets.
    resp = client.post(
        "/api/v1/deployments",
        json={"package_id": pkg_id, "target_type": "group", "target_value": "empty-group-id"},
        headers=_auth("operator"),
    )
    assert resp.status_code == 400
