"""Pluggable MQTT authentication with Unitree as the default provider."""

import hashlib
import random
import re
import string
from typing import Protocol


class AuthProvider(Protocol):
    def authenticate(self, username: str, password: str, client_id: str) -> tuple[bool, str | None, str]:
        """Returns (accepted, device_identifier, reason)."""
        ...


PASSWORD_PATTERN = re.compile(r"^1\|([0-9a-f]{32})\|([A-Za-z0-9]{4,32})$")


class UnitreeAuthProvider:
    """Authenticates using Unitree's serial-based MD5 scheme.

    password = "1|<md5_hex>|<nonce>"
    md5_hex  = MD5("unitree-" + serial + "-" + nonce)
    """

    @staticmethod
    def compute_md5(serial: str, nonce: str) -> str:
        return hashlib.md5(f"unitree-{serial}-{nonce}".encode()).hexdigest()

    @staticmethod
    def generate_nonce(length: int = 8) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=length))

    @staticmethod
    def generate_password(serial: str, nonce: str | None = None) -> str:
        if nonce is None:
            nonce = UnitreeAuthProvider.generate_nonce()
        md5_hex = UnitreeAuthProvider.compute_md5(serial, nonce)
        return f"1|{md5_hex}|{nonce}"

    @staticmethod
    def parse_client_id(client_id: str) -> str | None:
        if not client_id.startswith("unitree_robot_"):
            return None
        rest = client_id[len("unitree_robot_"):]
        if "@" in rest:
            rest = rest.split("@", 1)[0]
        return rest if rest else None

    def authenticate(self, username: str, password: str, client_id: str) -> tuple[bool, str | None, str]:
        serial = self.parse_client_id(client_id)
        if serial is None:
            return False, None, "invalid client_id format"
        if username != serial:
            return False, None, "username does not match client_id serial"
        m = PASSWORD_PATTERN.match(password)
        if not m:
            return False, None, "invalid password format"
        provided_md5 = m.group(1)
        nonce = m.group(2)
        expected_md5 = self.compute_md5(serial, nonce)
        if provided_md5 != expected_md5:
            return False, None, "MD5 validation failed"
        return True, serial, "authenticated"


class NoAuthProvider:
    """Accepts all connections. Extracts serial from client_id or username."""

    def authenticate(self, username: str, password: str, client_id: str) -> tuple[bool, str | None, str]:
        serial = UnitreeAuthProvider.parse_client_id(client_id) or username or "unknown"
        return True, serial, "no-auth"
