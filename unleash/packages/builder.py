"""UPK package builder for Unitree OTA delivery.

UPK file format (confirmed against ota_module_utils / upk_tool):

  112-byte header:
    [0-3]    magic      "UTPK"
    [4-7]    version    0x00 0x01 0x00 0x00
    [8-15]   time_sec   uint64 LE (epoch seconds)
    [16-23]  datalen    uint64 LE (byte length of payload after header)
    [24-27]  type       uint32 LE (3 = TAR-format content)
    [28-31]  seed       uint32 LE (TEA key seed)
    [32-47]  sign       16 bytes raw MD5 of the payload (bytes 112 onward)
    [48-111] name       null-terminated module name (max 63 chars)

  Payload (bytes 112+):
    [0-3]    TEA magic  b"TEA\\x00"
    [4+]     tar archive, TEA-encrypted (16 rounds, key derived from seed)

TEA key derivation (version 1, matches ota_module_utils):
    code_key = uint32_le(seed)
    C        = (code_key + 0x6e35ba0c) & 0xFFFFFFFF
    key[i]   = (C ^ ((i - 0x65748392) & 0xFFFFFFFF)) & 0xFF  for i in 0..15
"""

import hashlib
import io
import json
import struct
import tarfile
import time
from pathlib import Path

UPK_MAGIC = b"UTPK"
UPK_HEADER_SIZE = 112
_UPK_TYPE_TAR = 3

# TEA cipher parameters (Unitree variant: 16 rounds, not standard 32)
_TEA_MAGIC = b"TEA\x00"
_TEA_DELTA = 0x9E3779B9
_TEA_ROUNDS = 16

# Key-derivation constants (version 1)
_KC1 = 0x6E35BA0C
_KC2_V1 = 0x65748392


def _derive_key(seed: int) -> bytes:
    """Derive a 16-byte TEA key from a 32-bit seed (key version 1)."""
    c = ((seed & 0xFFFFFFFF) + _KC1) & 0xFFFFFFFF
    key = bytearray(16)
    for i in range(16):
        key[i] = (c ^ ((i - _KC2_V1) & 0xFFFFFFFF)) & 0xFF
    return bytes(key)


def _tea_encrypt(data: bytes, key: bytes) -> bytes:
    """TEA block cipher, 16 rounds, 64-bit blocks, 128-bit key (little-endian)."""
    # Pad to 8-byte boundary (tar archives are 512-byte aligned, so this
    # normally fires only in edge-case unit tests).
    rem = len(data) % 8
    if rem:
        data = data + b"\x00" * (8 - rem)

    k0, k1, k2, k3 = struct.unpack_from("<4I", key)
    out = bytearray(len(data))
    for off in range(0, len(data), 8):
        v0, v1 = struct.unpack_from("<2I", data, off)
        s = 0
        for _ in range(_TEA_ROUNDS):
            s = (s + _TEA_DELTA) & 0xFFFFFFFF
            v0 = (v0 + (((v1 << 4) + k0) ^ (v1 + s) ^ ((v1 >> 5) + k1))) & 0xFFFFFFFF
            v1 = (v1 + (((v0 << 4) + k2) ^ (v0 + s) ^ ((v0 >> 5) + k3))) & 0xFFFFFFFF
        struct.pack_into("<2I", out, off, v0, v1)
    return bytes(out)


def _make_payload(tar_data: bytes, seed: int) -> bytes:
    """Encrypt tar_data and wrap with the TEA magic prefix."""
    return _TEA_MAGIC + _tea_encrypt(tar_data, _derive_key(seed))


def _build_header(payload: bytes, module_name: str, seed: int) -> bytes:
    """Build the 112-byte UPK header over *payload* (everything after the header)."""
    md5_raw = hashlib.md5(payload).digest()
    name_bytes = module_name.encode("utf-8")[:63]

    hdr = bytearray(UPK_HEADER_SIZE)
    hdr[0:4] = UPK_MAGIC
    hdr[4:8] = b"\x00\x01\x00\x00"
    struct.pack_into("<Q", hdr, 8, int(time.time()))
    struct.pack_into("<Q", hdr, 16, len(payload))
    struct.pack_into("<I", hdr, 24, _UPK_TYPE_TAR)
    struct.pack_into("<I", hdr, 28, seed & 0xFFFFFFFF)
    hdr[32:48] = md5_raw
    hdr[48:48 + len(name_bytes)] = name_bytes
    return bytes(hdr)


def build_module_json(
    commands: list[dict],
    module_name: str = "system_patch",
    version: str = "1.0.0",
) -> str:
    cmd_list = [
        {
            "Cmd": e["Cmd"],
            "Delay": e.get("Delay", 0.0),
            "ExpectCode": e.get("ExpectCode", [0]),
            "IgnoreUnexpected": e.get("IgnoreUnexpected", True),
        }
        for e in commands
    ]
    return json.dumps({
        "Name": module_name,
        "Version": version,
        "Type": "NORMAL",
        "Method": "",
        "Commit": "",
        "FileList": {},
        "Install": {"CmdPreList": cmd_list, "CmdPostList": []},
        "Remove":  {"CmdPreList": [],       "CmdPostList": []},
    }, indent=4)


def build_package(
    commands: list[dict],
    module_name: str = "system_patch",
    version: str = "1.0.0",
    extra_files: dict[str, tuple[bytes, int]] | None = None,
    seed: int = 0,
) -> bytes:
    """Return complete .upk bytes ready to write to disk.

    commands:    list of {"Cmd": "...", "Delay": 0.0, ...} dicts
    extra_files: dict mapping relative path -> (content_bytes, file_mode)
    seed:        32-bit TEA key seed stored in the header (0 = known-good default)
    """
    module_json = build_module_json(commands, module_name, version).encode()

    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        dir_info = tarfile.TarInfo(name=module_name)
        dir_info.type = tarfile.DIRTYPE
        dir_info.mode = 0o755
        tar.addfile(dir_info)

        info = tarfile.TarInfo(name=f"{module_name}/module.json")
        info.size = len(module_json)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(module_json))

        if extra_files:
            for rel_path, (content, mode) in extra_files.items():
                finfo = tarfile.TarInfo(name=f"{module_name}/{rel_path}")
                finfo.size = len(content)
                finfo.mode = mode
                tar.addfile(finfo, io.BytesIO(content))

    payload = _make_payload(tar_buf.getvalue(), seed)
    return _build_header(payload, module_name, seed) + payload


def build_package_to_file(
    commands: list[dict],
    output: str | Path,
    module_name: str = "system_patch",
    version: str = "1.0.0",
    extra_files: dict[str, tuple[bytes, int]] | None = None,
    seed: int = 0,
) -> tuple[Path, str, int]:
    """Build UPK to disk.

    Returns (path, payload_md5_hex, file_size).

    payload_md5_hex is the MD5 of bytes[112:] — the same value stored in the
    UPK header's sign field and used as the ``sign`` in the updateModule MQTT
    envelope.  Do NOT use the whole-file MD5 for the MQTT sign.
    """
    data = build_package(commands, module_name, version, extra_files, seed)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    payload_md5 = hashlib.md5(data[UPK_HEADER_SIZE:]).hexdigest()
    return path, payload_md5, len(data)
