"""OTA deployment orchestration and the UPK file server.

Async paths are driven via asyncio.run() so we don't need a pytest-asyncio
plugin. Each test gets its own throwaway SQLite file.
"""

import asyncio
import hashlib
import json
import struct

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from unleash.db.models import Base, Deployment, DeploymentTarget, Package, Robot
from unleash.packages.builder import (
    UPK_HEADER_SIZE, _TEA_MAGIC, _derive_key, _tea_encrypt,
    build_module_json, build_package,
)
from unleash.packages.deployment import DeploymentService, parse_serials
from unleash.packages.file_server import UPKFileServer

UPK_NAME = "patch_1.0.0.upk"


class FakeBroker:
    def __init__(self, connected):
        self.clients = {s: object() for s in connected}
        self.sent = []

    async def send_command(self, serial, payload):
        self.sent.append((serial, payload))
        return True


async def _make_db(db_path, upk_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(Robot(serial="R1", status="online", ip_address="10.0.0.5"))
        s.add(Robot(serial="R2", status="offline", ip_address="10.0.0.6"))
        s.add(Package(
            name="patch", version="1.0.0", module_name="system_patch",
            commands_json="[]", file_hash="abc123", file_size=42,
            file_path=str(upk_path),
        ))
        await s.commit()
        pkg_id = (await s.execute(select(Package.id))).scalar_one()
    return engine, factory, pkg_id


# --------------------------------------------------------------------------- #
#  Pure helper
# --------------------------------------------------------------------------- #

def test_parse_serials():
    assert parse_serials('["a", "b"]') == ["a", "b"]
    assert parse_serials("a, b ,c") == ["a", "b", "c"]
    assert parse_serials("") == []
    assert parse_serials(None) == []


# --------------------------------------------------------------------------- #
#  Dispatch
# --------------------------------------------------------------------------- #

def test_dispatch_targets_connected_and_marks_offline(tmp_path):
    upk = tmp_path / UPK_NAME
    upk.write_bytes(b"upk-bytes")

    async def run():
        engine, factory, pkg_id = await _make_db(tmp_path / "db.sqlite", upk)
        fake = FakeBroker(connected={"R1"})  # R2 is offline
        svc = DeploymentService(fake, factory, advertise_host="10.0.0.1", upk_port=8899)

        async with factory() as s:
            pkg = await s.get(Package, pkg_id)
            dep = await svc.create(s, pkg, "all", None, "immediate", "user1")
            dep_id = dep.id

        await svc.dispatch(dep_id)

        async with factory() as s:
            targets = {
                t.robot_serial: t for t in
                (await s.execute(select(DeploymentTarget).where(
                    DeploymentTarget.deployment_id == dep_id))).scalars().all()
            }
            assert targets["R1"].status == "sent"
            assert targets["R2"].status == "failed"
            assert targets["R2"].error_message == "robot not connected"
            dep = await s.get(Deployment, dep_id)
            assert dep.status == "in_progress"
            r1 = (await s.execute(select(Robot).where(Robot.serial == "R1"))).scalar_one()
            assert r1.status == "updating"

        # Exactly one command, to the connected robot, with a correct envelope.
        assert len(fake.sent) == 1
        serial, payload = fake.sent[0]
        assert serial == "R1"
        env = json.loads(payload)
        assert env["cmd"] == "updateModule"
        assert env["module"]["url"] == f"http://10.0.0.1:8899/{UPK_NAME}"
        assert env["module"]["sign"] == "abc123"
        assert env["module"]["size"] == 42
        await engine.dispose()

    asyncio.run(run())


def test_download_marks_downloading(tmp_path):
    upk = tmp_path / UPK_NAME
    upk.write_bytes(b"upk-bytes")

    async def run():
        engine, factory, pkg_id = await _make_db(tmp_path / "db.sqlite", upk)
        svc = DeploymentService(FakeBroker({"R1"}), factory, "10.0.0.1", 8899)
        async with factory() as s:
            pkg = await s.get(Package, pkg_id)
            dep = await svc.create(s, pkg, "serial_list", "R1", "immediate", "u")
            dep_id = dep.id
        await svc.dispatch(dep_id)

        await svc.handle_download(UPK_NAME, "10.0.0.5")  # R1's IP

        async with factory() as s:
            t = (await s.execute(select(DeploymentTarget).where(
                DeploymentTarget.robot_serial == "R1"))).scalar_one()
            assert t.status == "downloading"
            assert t.download_count == 1
        await engine.dispose()

    asyncio.run(run())


def _report_version(modules: list[dict]) -> bytes:
    """Build a reportVersion payload as the Go2 firmware sends it."""
    return json.dumps({"cmd": "reportVersion", "msgId": "x", "modules": modules}).encode()


def test_report_completes_deployment(tmp_path):
    upk = tmp_path / UPK_NAME
    upk.write_bytes(b"upk-bytes")

    async def run():
        engine, factory, pkg_id = await _make_db(tmp_path / "db.sqlite", upk)
        svc = DeploymentService(FakeBroker({"R1"}), factory, "10.0.0.1", 8899)
        async with factory() as s:
            pkg = await s.get(Package, pkg_id)
            dep = await svc.create(s, pkg, "serial_list", "R1", "immediate", "u")
            dep_id = dep.id
        await svc.dispatch(dep_id)

        # Junk / wrong cmd must never raise or change state.
        for bad in [
            b"not json",
            json.dumps({"cmd": "updateModule", "code": 0}).encode(),   # old wrong format
            json.dumps({"cmd": "reportVersion", "modules": []}).encode(),  # empty list
            _report_version([{"moduleName": "other_module", "version": "1.0.0", "code": 0}]),
            _report_version([{"moduleName": "system_patch", "version": "9.9.9", "code": 0}]),
        ]:
            await svc.handle_report("R1", "t", bad)
        async with factory() as s:
            t = (await s.execute(select(DeploymentTarget).where(
                DeploymentTarget.robot_serial == "R1"))).scalar_one()
            assert t.status == "sent", f"status changed unexpectedly on bad input"

        # A correct reportVersion with code=0 completes the target and deployment.
        await svc.handle_report("R1", "t", _report_version([
            {"moduleName": "system_patch", "version": "1.0.0", "code": 0},
            {"moduleName": "other_module",  "version": "2.0.0", "code": 0},  # unrelated — ignored
        ]))
        async with factory() as s:
            t = (await s.execute(select(DeploymentTarget).where(
                DeploymentTarget.robot_serial == "R1"))).scalar_one()
            assert t.status == "completed"
            dep = await s.get(Deployment, dep_id)
            assert dep.status == "completed"
            assert dep.completed_at is not None
        await engine.dispose()

    asyncio.run(run())


def test_report_failure(tmp_path):
    upk = tmp_path / UPK_NAME
    upk.write_bytes(b"upk-bytes")

    async def run():
        engine, factory, pkg_id = await _make_db(tmp_path / "db.sqlite", upk)
        svc = DeploymentService(FakeBroker({"R1"}), factory, "10.0.0.1", 8899)
        async with factory() as s:
            pkg = await s.get(Package, pkg_id)
            dep = await svc.create(s, pkg, "serial_list", "R1", "immediate", "u")
            dep_id = dep.id
        await svc.dispatch(dep_id)

        await svc.handle_report("R1", "t", _report_version([
            {"moduleName": "system_patch", "version": "1.0.0", "code": 1},
        ]))
        async with factory() as s:
            t = (await s.execute(select(DeploymentTarget).where(
                DeploymentTarget.robot_serial == "R1"))).scalar_one()
            assert t.status == "failed"
            assert "1" in t.error_message
            r1 = (await s.execute(select(Robot).where(Robot.serial == "R1"))).scalar_one()
            assert r1.status == "error"
            dep = await s.get(Deployment, dep_id)
            assert dep.status == "failed"
        await engine.dispose()

    asyncio.run(run())


# --------------------------------------------------------------------------- #
#  UPK builder format
# --------------------------------------------------------------------------- #

def _tea_decrypt(data: bytes, key: bytes) -> bytes:
    """TEA block cipher decrypt (16 rounds, matching the builder's encrypt)."""
    rem = len(data) % 8
    if rem:
        data = data + b"\x00" * (8 - rem)
    k0, k1, k2, k3 = struct.unpack_from("<4I", key)
    delta = 0x9E3779B9
    rounds = 16
    out = bytearray(len(data))
    for off in range(0, len(data), 8):
        v0, v1 = struct.unpack_from("<2I", data, off)
        s = (delta * rounds) & 0xFFFFFFFF
        for _ in range(rounds):
            v1 = (v1 - (((v0 << 4) + k2) ^ (v0 + s) ^ ((v0 >> 5) + k3))) & 0xFFFFFFFF
            v0 = (v0 - (((v1 << 4) + k0) ^ (v1 + s) ^ ((v1 >> 5) + k1))) & 0xFFFFFFFF
            s = (s - delta) & 0xFFFFFFFF
        struct.pack_into("<2I", out, off, v0, v1)
    return bytes(out)


def test_upk_builder_format(tmp_path):
    """Verify the built .upk matches the on-device format from firmware recon."""
    import io, tarfile as tf

    data = build_package(
        commands=[{"Cmd": "echo hello", "ExpectCode": [0]}],
        module_name="system_patch",
        version="1.0.0",
        seed=0,
    )

    # Header fields
    assert data[0:4] == b"UTPK"
    assert data[4:8] == b"\x00\x01\x00\x00"
    assert struct.unpack_from("<I", data, 24)[0] == 3, "type must be 3 (TAR)"
    assert struct.unpack_from("<I", data, 28)[0] == 0, "seed must be 0"

    payload = data[UPK_HEADER_SIZE:]
    datalen = struct.unpack_from("<Q", data, 16)[0]
    assert datalen == len(payload), "datalen matches actual payload length"

    # Payload starts with TEA magic
    assert payload[:4] == _TEA_MAGIC

    # Header sign == md5(payload)
    assert data[32:48] == hashlib.md5(payload).digest()

    # Decrypt and verify the embedded tar contains module.json
    key = _derive_key(0)
    tar_data = _tea_decrypt(payload[4:], key)
    with tf.open(fileobj=io.BytesIO(tar_data)) as tar:
        names = tar.getnames()
    assert any(n.endswith("module.json") for n in names)

    # build_package_to_file returns payload md5 (not whole-file md5)
    from unleash.packages.builder import build_package_to_file
    _, returned_hash, _ = build_package_to_file(
        commands=[], output=tmp_path / "test.upk", module_name="m", version="0.1"
    )
    built = (tmp_path / "test.upk").read_bytes()
    assert returned_hash == hashlib.md5(built[UPK_HEADER_SIZE:]).hexdigest()
    assert returned_hash != hashlib.md5(built).hexdigest(), "must NOT be whole-file md5"


# --------------------------------------------------------------------------- #
#  UPK file server
# --------------------------------------------------------------------------- #

def test_file_server_serves_upk_and_rejects_others(tmp_path):
    (tmp_path / UPK_NAME).write_bytes(b"PACKAGE-DATA")
    (tmp_path / "secret.txt").write_bytes(b"nope")
    downloads = []

    async def hook(filename, ip):
        downloads.append((filename, ip))

    async def http_get(port, path):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(-1), timeout=5)
        writer.close()
        return data

    async def run():
        server = UPKFileServer(tmp_path, host="127.0.0.1", port=0, on_download=hook)
        await server.start()
        port = server._server.sockets[0].getsockname()[1]

        ok = await http_get(port, f"/{UPK_NAME}")
        assert ok.split(b"\r\n")[0] == b"HTTP/1.1 200 OK"
        assert ok.endswith(b"PACKAGE-DATA")

        # Non-.upk is rejected even though the file exists.
        assert b"404" in (await http_get(port, "/secret.txt")).split(b"\r\n")[0]
        # Missing file.
        assert b"404" in (await http_get(port, "/missing.upk")).split(b"\r\n")[0]
        # Path traversal collapses to a basename -> not found.
        assert b"404" in (await http_get(port, "/../../etc/passwd")).split(b"\r\n")[0]

        await server.stop()
        assert downloads == [(UPK_NAME, "127.0.0.1")]

    asyncio.run(run())
