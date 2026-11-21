"""MQTT OTA envelope builders for the Unitree updateModule command."""

import json
import time


def _msg_id() -> str:
    return str(int(time.time() * 1000000))


def build_update_envelope(
    module_name: str,
    version: str,
    url: str,
    sign: str = "",
    size: int = 0,
    mqtt_module_name: str | None = None,
) -> str:
    """Build an updateModule MQTT envelope.

    mqtt_module_name: if set, uses a different name in the MQTT JSON than the UPK
    header name. This avoids the download path collision where ota_engine_utils
    saves the downloaded file to a path that conflicts with the tar directory name.
    """
    mn = mqtt_module_name or module_name
    return json.dumps({
        "cmd": "updateModule",
        "msgId": _msg_id(),
        "targetModuleVersion": version,
        "module": {
            "moduleName": mn,
            "name": mn,
            "version": version,
            "url": url,
            "sign": sign,
            "size": size,
        },
    })
