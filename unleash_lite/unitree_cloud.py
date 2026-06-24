"""
Unitree cloud API client for fetching the per-device AES-128 key.

The key is required for the data2=3 WebRTC handshake on Go2 firmware
>= 1.1.15. It's stored on the robot at /unitree/etc/key/aes_key.bin
but also available from the cloud if you have owner account credentials.

Uses curl_cffi because Unitree's API is behind Cloudflare TLS/JA3
fingerprinting that blocks plain requests.
"""

import hashlib
import time
import uuid

from curl_cffi import requests as cffi_requests


APP_SIGN_SECRET = "XyvkwK45hp5PHfA8"

BASE_URLS = {
    "global": "https://global-robot-api.unitree.com/",
    "cn": "https://robot-api.unitree.com/",
}

_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "DeviceId": "Samsung/Samsung/SM-S931B/s24/14/34",
    "DevicePlatform": "Android",
    "DeviceModel": "SM-S931B",
    "SystemVersion": "34",
    "AppVersion": "1.11.4",
    "AppLocale": "en_US",
    "Channel": "UMENG_CHANNEL",
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; SM-S931B Build/AP3A.240905.015.A2; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/127.0.6533.103 "
        "Mobile Safari/537.36"
    ),
}


class UnitreeCloudError(RuntimeError):
    def __init__(self, action, code, msg):
        super().__init__(f"{action} failed: code={code} msg={msg!r}")
        self.action = action
        self.code = code
        self.msg = msg


class UnitreeCloud:

    def __init__(self, region="global", device_type="Go2", access_token=""):
        self.region = region
        self.device_type = device_type
        self.base_url = BASE_URLS[region]
        self.access_token = access_token
        self._session = cffi_requests.Session(impersonate="chrome120")

    def _headers(self):
        ts = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        sign = hashlib.md5(f"{APP_SIGN_SECRET}{ts}{nonce}".encode()).hexdigest()
        return {
            **_HEADERS,
            "AppTimezone": time.strftime("%z") or "UTC",
            "AppTimestamp": ts,
            "AppNonce": nonce,
            "AppSign": sign,
            "AppName": self.device_type,
            "Token": self.access_token,
        }

    def _post(self, path, body=None):
        url = self.base_url + path
        resp = self._session.post(url, data=body or {}, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _get(self, path, params=None):
        url = self.base_url + path
        resp = self._session.get(url, params=params or {}, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _check(self, result, action):
        if result.get("code") != 100:
            raise UnitreeCloudError(action, result.get("code"), result.get("errorMsg", ""))
        return result.get("data")

    def login(self, email, password):
        result = self._post("login/email", {
            "email": email,
            "password": hashlib.md5(password.encode()).hexdigest(),
        })
        data = self._check(result, "login")
        self.access_token = data.get("accessToken", "")
        return self.access_token

    def list_devices(self):
        result = self._get("device/bind/list")
        data = self._check(result, "device/bind/list") or []
        return data


def fetch_aes_key(email, password, sn=None, region="global", device_type="Go2"):
    """Login and return the AES key(s) from device/bind/list.

    If sn is specified, returns just that key as a string.
    If sn is None, returns the full device list.
    """
    cloud = UnitreeCloud(region=region, device_type=device_type)
    cloud.login(email, password)
    devices = cloud.list_devices()

    if sn:
        for d in devices:
            if d.get("sn") == sn:
                key = d.get("key", "") or d.get("gcm_key", "")
                if not key:
                    raise UnitreeCloudError(
                        "fetch_aes_key", 0,
                        f"Device {sn} is bound but the cloud returned an empty key. "
                        f"The robot may be on firmware older than 1.1.15."
                    )
                return key
        raise UnitreeCloudError(
            "fetch_aes_key", 0,
            f"SN {sn} is not bound to this account (region={region!r}). "
            f"Pair the robot through the Unitree app first."
        )

    return devices
