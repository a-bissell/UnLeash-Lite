"""
R1 audio_detect shell client.

Connects to the audio_detect.py socket listener (port 8888) that is
activated on the R1 by pressing L1+L2+Start on the controller. The
listener runs as root and accepts JSON commands over a simple TCP
protocol with a hardcoded auth key.

Protocol:
  1. Connect to <robot_ip>:8888
  2. Send auth key ("unitree123")
  3. Receive "AUTH_SUCCESS"
  4. Send JSON commands, receive responses

IMPORTANT: exec_cmd only returns "CMD_EXECUTED" — NOT stdout. To capture
command output, we wrap commands in a shell redirect, then download the
output file via the download_file command. This pattern is from thomas
flayols' r1_audio_detect_shell.py.

Supported command types:
  - exec_cmd: {"type": "exec_cmd", "cmd": "<shell command>"}
  - download_file: {"type": "download_file", "path": "<path>"}
  - heartbeat: {"type": "heartbeat"}
"""

import json
import shlex
import socket
import time
import uuid

AUTH_KEY = "unitree123"
DEFAULT_PORT = 8888
BUFFER_SIZE = 4096
CONNECT_TIMEOUT = 5
RECV_TIMEOUT = 10


class R1AudioDetectError(Exception):
    pass


class R1FileNotFound(R1AudioDetectError):
    pass


class R1RemoteTimeout(R1AudioDetectError):
    pass


class R1AudioDetectClient:
    """Client for the R1 audio_detect.py socket listener."""

    def __init__(self, robot_ip, port=DEFAULT_PORT):
        self.robot_ip = robot_ip
        self.port = port
        self._sock = None

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(CONNECT_TIMEOUT)
        try:
            self._sock.connect((self.robot_ip, self.port))
        except (ConnectionRefusedError, OSError) as e:
            raise R1AudioDetectError(
                f"Cannot connect to {self.robot_ip}:{self.port} — "
                f"is the listener active? (L1+L2+Start)"
            ) from e

        self._sock.settimeout(RECV_TIMEOUT)
        self._sock.sendall(AUTH_KEY.encode("utf-8"))
        resp = self._sock.recv(BUFFER_SIZE).decode("utf-8")
        if resp != "AUTH_SUCCESS":
            raise R1AudioDetectError(f"Authentication failed: {resp}")

    def exec_cmd(self, cmd):
        """Send exec_cmd. Returns "CMD_EXECUTED" (NOT stdout)."""
        payload = json.dumps({"type": "exec_cmd", "cmd": cmd})
        self._sock.sendall(payload.encode("utf-8"))
        resp = self._sock.recv(BUFFER_SIZE).decode("utf-8")
        if resp != "CMD_EXECUTED":
            raise R1AudioDetectError(f"Unexpected exec_cmd response: {resp!r}")
        return resp

    def download_file(self, path):
        """Download a file from the robot. Returns bytes or raises R1FileNotFound."""
        payload = json.dumps({"type": "download_file", "path": path})
        self._sock.sendall(payload.encode("utf-8"))
        resp = self._sock.recv(BUFFER_SIZE).decode("utf-8")
        if resp == "FILE_NOT_FOUND":
            raise R1FileNotFound(path)
        file_size = int(resp)
        self._sock.sendall(b"OK")
        data = b""
        while len(data) < file_size:
            chunk = self._sock.recv(min(BUFFER_SIZE, file_size - len(data)))
            if not chunk:
                raise R1AudioDetectError(
                    f"Connection closed with {file_size - len(data)} bytes remaining"
                )
            data += chunk
        return data

    def heartbeat(self):
        payload = json.dumps({"type": "heartbeat"})
        self._sock.sendall(payload.encode("utf-8"))
        resp = self._sock.recv(BUFFER_SIZE).decode("utf-8")
        return resp == "PONG"

    def run(self, command, cwd="/", timeout=20.0, poll_interval=0.15):
        """Run a command and capture stdout/stderr + exit code.

        Wraps the command in a shell redirect, polls for completion via
        a sentinel file, then downloads the output. Returns (output, returncode).
        """
        token = uuid.uuid4().hex
        base = f"/tmp/_unleash_{token}"
        out_path = f"{base}.out"
        status_path = f"{base}.rc"
        done_path = f"{base}.done"

        script = "\n".join([
            f"cd {shlex.quote(cwd)}",
            command,
            'rc="$?"',
            f"printf '%s\\n' \"$rc\" > {shlex.quote(status_path)}",
            f"touch {shlex.quote(done_path)}",
        ])
        wrapped = f"sh -c {shlex.quote(script)} > {shlex.quote(out_path)} 2>&1"

        self.exec_cmd(wrapped)

        deadline = time.monotonic() + timeout
        while True:
            try:
                self.download_file(done_path)
                break
            except R1FileNotFound:
                if time.monotonic() >= deadline:
                    raise R1RemoteTimeout(
                        f"Command did not finish within {timeout:.0f}s"
                    )
                time.sleep(poll_interval)

        output = self.download_file(out_path)

        try:
            rc_text = self.download_file(status_path).decode("utf-8").strip()
            returncode = int(rc_text)
        except (R1FileNotFound, ValueError):
            returncode = None

        # Cleanup temp files
        cleanup = f"rm -f {shlex.quote(out_path)} {shlex.quote(status_path)} {shlex.quote(done_path)}"
        try:
            self.exec_cmd(cleanup)
        except R1AudioDetectError:
            pass

        return output.decode("utf-8", errors="replace"), returncode

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()


def probe_listener(robot_ip, port=DEFAULT_PORT, timeout=3):
    """Check if audio_detect listener is active (port open + auth works)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((robot_ip, port))
        s.sendall(AUTH_KEY.encode("utf-8"))
        resp = s.recv(BUFFER_SIZE).decode("utf-8")
        s.close()
        return resp == "AUTH_SUCCESS"
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def exec_shell(robot_ip, cmd, cwd="/", port=DEFAULT_PORT, timeout=20.0):
    """One-shot: connect, auth, run a command with output capture, close."""
    with R1AudioDetectClient(robot_ip, port) as client:
        output, returncode = client.run(cmd, cwd=cwd, timeout=timeout)
        return output, returncode


def interactive_shell(robot_ip, port=DEFAULT_PORT):
    """Interactive shell session with output capture."""
    print(f"  Connecting to {robot_ip}:{port}...")
    with R1AudioDetectClient(robot_ip, port) as client:
        print(f"  Connected! Type commands, 'exit' to quit.")
        print(f"  (stdout/stderr captured via temp files)\n")
        cwd = "/"
        while True:
            try:
                cmd = input(f"  \033[1;36mr1:{cwd}$\033[0m ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not cmd or cmd in ("exit", "quit", "q"):
                break
            try:
                output, returncode = client.run(cmd, cwd=cwd)
                if output:
                    for line in output.rstrip("\n").split("\n"):
                        print(f"  {line}")
                if returncode is not None and returncode != 0:
                    print(f"  \033[1;33m[exit {returncode}]\033[0m")
            except R1RemoteTimeout:
                print("  \033[1;31m[timeout]\033[0m")
            except R1AudioDetectError as e:
                print(f"  \033[1;31m[error: {e}]\033[0m")
