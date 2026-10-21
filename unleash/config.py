"""Central configuration via environment variables."""

import secrets
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

_SECRET_SENTINEL = "change-me-in-production"


class Settings(BaseSettings):
    model_config = {"env_prefix": "UNLEASH_"}

    # API
    host: str = "0.0.0.0"
    api_port: int = 8080
    secret_key: str = _SECRET_SENTINEL
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # CORS — origins allowed to call the API from a browser.
    # The bundled SPA is served same-origin, so this only matters for the
    # standalone Vite dev server. Override via UNLEASH_CORS_ORIGINS (JSON list).
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # MQTT Broker
    mqtt_host: str = "0.0.0.0"
    mqtt_port: int = 17883
    mqtt_use_tls: bool = True
    mqtt_require_auth: bool = True
    mqtt_cert_path: str | None = None
    mqtt_key_path: str | None = None

    # Database
    database_url: str = "sqlite+aiosqlite:///./unleash.db"

    # Data paths
    data_dir: Path = Path("./data")
    package_dir: Path = Path("./data/packages")

    # UPK file server (serves .upk packages to robots for OTA delivery)
    upk_server_host: str = "0.0.0.0"      # bind address
    upk_server_port: int = 8899
    # Host/IP that robots use to reach the UPK file server. This goes into the
    # download URL inside the updateModule command, so it must be reachable
    # *from the robot*. Override via UNLEASH_UPK_ADVERTISE_HOST in production.
    upk_advertise_host: str = "127.0.0.1"

    @model_validator(mode="after")
    def _ensure_secret_key(self):
        """Never run on a static, publicly-known signing key.

        If the operator hasn't supplied UNLEASH_SECRET_KEY, generate a random key
        on first boot and persist it under data_dir so issued tokens survive
        restarts. An explicit key (env/.env) always wins and is left untouched.
        """
        if self.secret_key != _SECRET_SENTINEL:
            return self
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key_file = self.data_dir / "secret_key"
        if key_file.exists():
            self.secret_key = key_file.read_text().strip()
        else:
            generated = secrets.token_urlsafe(48)
            key_file.write_text(generated)
            try:
                key_file.chmod(0o600)
            except OSError:
                pass
            self.secret_key = generated
        return self


settings = Settings()
