"""Auth enforcement on the realtime WebSocket endpoints.

These endpoints stream live robot serials, IPs, and message payloads, so they
must reject unauthenticated clients. The token rides in a ?token= query param
because browsers can't set Authorization headers on a WS handshake.

The app's lifespan starts the MQTT broker; we deliberately do NOT enter it
(no `with TestClient(...)`) because the WS routes only depend on token
decoding, not on the broker or DB.
"""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from unleash.app import create_app
from unleash.auth.jwt_handler import create_access_token, create_refresh_token

WS_PATHS = ["/ws/events", "/ws/fleet"]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def access_token() -> str:
    return create_access_token(user_id="u1", username="alice", role="viewer")


@pytest.mark.parametrize("path", WS_PATHS)
def test_valid_access_token_is_accepted(client, access_token, path):
    with client.websocket_connect(f"{path}?token={access_token}") as ws:
        # Reaching here means the handshake completed (server called accept()).
        ws.send_text("ping")


@pytest.mark.parametrize("path", WS_PATHS)
def test_missing_token_is_rejected(client, path):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(path):
            pass
    assert exc.value.code == 4401


@pytest.mark.parametrize("path", WS_PATHS)
def test_garbage_token_is_rejected(client, path):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{path}?token=not-a-real-jwt"):
            pass
    assert exc.value.code == 4401


@pytest.mark.parametrize("path", WS_PATHS)
def test_refresh_token_is_rejected(client, path):
    # A refresh token is a valid JWT but the wrong type for this endpoint.
    refresh = create_refresh_token(user_id="u1")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{path}?token={refresh}"):
            pass
    assert exc.value.code == 4401
