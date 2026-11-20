"""TLS certificate generation for the MQTT broker."""

import subprocess
from pathlib import Path

DEFAULT_CERT_DIR = Path(__file__).parent.parent.parent / "data" / "certs"


def generate_self_signed(
    cert_dir: Path | None = None,
    hostname: str = "global-robot-mqtt.unitree.com",
    days: int = 3650,
) -> tuple[Path, Path]:
    cert_dir = cert_dir or DEFAULT_CERT_DIR
    cert_dir.mkdir(parents=True, exist_ok=True)

    ca_key = cert_dir / "ca.key"
    ca_cert = cert_dir / "ca.pem"
    server_key = cert_dir / "server.key"
    server_cert = cert_dir / "server.pem"
    server_csr = cert_dir / "server.csr"

    if server_cert.exists() and server_key.exists():
        return server_cert, server_key

    subprocess.run([
        "openssl", "req", "-x509", "-new", "-nodes",
        "-keyout", str(ca_key), "-out", str(ca_cert),
        "-days", str(days), "-subj", "/CN=UnLeash CA",
    ], check=True, capture_output=True)

    subprocess.run([
        "openssl", "req", "-new", "-nodes",
        "-keyout", str(server_key), "-out", str(server_csr),
        "-subj", f"/CN={hostname}",
    ], check=True, capture_output=True)

    ext_file = cert_dir / "ext.cnf"
    ext_file.write_text(
        f"subjectAltName=DNS:{hostname},DNS:robot-mqtt.unitree.com\n"
    )
    subprocess.run([
        "openssl", "x509", "-req", "-in", str(server_csr),
        "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
        "-out", str(server_cert), "-days", str(days),
        "-extfile", str(ext_file),
    ], check=True, capture_output=True)

    server_csr.unlink(missing_ok=True)
    ext_file.unlink(missing_ok=True)
    (cert_dir / "ca.srl").unlink(missing_ok=True)

    return server_cert, server_key
