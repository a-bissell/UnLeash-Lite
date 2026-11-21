"""Minimal HTTP server that delivers built .upk packages to robots for OTA.

The robot fetches a package from the URL embedded in the ``updateModule``
command. Robots have no API credentials, so this endpoint is intentionally
unauthenticated; it only serves ``*.upk`` files out of the package directory
and rejects anything else. A download fires the ``on_download`` hook so the
deployment layer can record progress.
"""

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger("unleash.upk")

DownloadHook = Callable[[str, str], Awaitable[None]]

_REASON = {200: "OK", 404: "Not Found", 405: "Method Not Allowed"}


class UPKFileServer:
    def __init__(
        self,
        package_dir: str | Path,
        host: str = "0.0.0.0",
        port: int = 8899,
        on_download: DownloadHook | None = None,
    ):
        self.package_dir = Path(package_dir)
        self.host = host
        self.port = port
        self.on_download = on_download
        self._server: asyncio.Server | None = None

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle, self.host, self.port, reuse_address=True
        )
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        logger.info(f"UPK file server listening on {addrs}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=15)
            # Drain the rest of the headers.
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=15)
                if line in (b"\r\n", b"\n", b""):
                    break

            parts = request_line.decode("latin-1").split()
            if len(parts) < 2 or parts[0] != "GET":
                await self._respond(writer, 405, b"method not allowed")
                return

            # Path().name strips any directory component, so traversal
            # (../../etc/passwd) collapses to a bare filename.
            filename = Path(parts[1].split("?", 1)[0]).name
            file_path = self.package_dir / filename
            if not filename.endswith(".upk") or not file_path.is_file():
                await self._respond(writer, 404, b"not found")
                return

            data = file_path.read_bytes()
            await self._respond(writer, 200, data, content_type="application/octet-stream")

            peer = writer.get_extra_info("peername")
            client_ip = peer[0] if peer else ""
            logger.info(f"UPK download: {filename} -> {client_ip} ({len(data)} bytes)")
            if self.on_download:
                try:
                    await self.on_download(filename, client_ip)
                except Exception:
                    logger.exception("on_download hook failed")
        except (asyncio.TimeoutError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _respond(self, writer, status: int, body: bytes, content_type: str = "text/plain"):
        head = (
            f"HTTP/1.1 {status} {_REASON.get(status, 'OK')}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("latin-1")
        writer.write(head + body)
        await writer.drain()
