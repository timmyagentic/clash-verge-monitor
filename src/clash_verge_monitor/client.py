from __future__ import annotations

import http.client
import json
import socket
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from .models import ConnectionSnapshot, ProcessLookup


DEFAULT_UNIX_SOCKET = "/tmp/verge/verge-mihomo.sock"


def controller_candidates() -> list[str]:
    """Only this user's service and known legacy sockets; never scan other users."""
    return list(dict.fromkeys([
        f"/var/run/clash-verge-service/users/{os.getuid()}/verge-mihomo.sock",
        str(Path(tempfile.gettempdir()) / "verge-mihomo.sock"),
        DEFAULT_UNIX_SOCKET,
    ]))


def needs_process_lookup(items: list[dict[str, Any]]) -> bool:
    for item in items:
        raw_metadata = item.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        process = str(metadata.get("process") or "").strip()
        process_path = str(metadata.get("processPath") or "").strip()
        if (not process or process.lower() == "unknown") and not process_path:
            return True
    return False


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.socket_path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


@dataclass(frozen=True)
class ControllerConfig:
    controller: str = "auto"
    secret: str | None = None
    timeout: float = 5.0

    def __post_init__(self):
        import math
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError('Controller timeout must be positive and finite')
        if self.is_http:
            parsed = urlparse(self.controller)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Use a plain controller URL and a separate secret file')

    @property
    def is_http(self) -> bool:
        return self.controller.startswith("http://") or self.controller.startswith("https://")

    @property
    def socket_path(self) -> str:
        if self.controller.startswith("unix://"):
            return self.controller[len("unix://") :]
        return self.controller


class MihomoClient:
    def __init__(self, config: ControllerConfig | None = None) -> None:
        self.config = config or ControllerConfig()
        self.resolved_controller = self.config.socket_path
        self.last_totals: tuple[int, int] | None = None

    @property
    def identity(self) -> str:
        try:
            stat = Path(self.resolved_controller).stat()
            return f"{self.resolved_controller}:{stat.st_dev}:{stat.st_ino}"
        except OSError:
            return self.resolved_controller

    def get_json(self, path: str) -> Any:
        if not path.startswith("/"):
            path = f"/{path}"
        headers = {"Host": "localhost"}
        if self.config.secret:
            headers["Authorization"] = f"Bearer {self.config.secret}"

        if self.config.is_http:
            return self._get_http(path, headers)
        if self.config.controller != "auto":
            return self._get_unix(path, headers)
        candidates = list(controller_candidates())
        if self.resolved_controller in candidates:
            candidates.remove(self.resolved_controller)
            candidates.insert(0, self.resolved_controller)
        for candidate in candidates:
            self.resolved_controller = candidate
            try:
                return self._get_unix(path, headers)
            except (OSError, http.client.HTTPException):
                continue
        raise ConnectionError("No reachable Clash controller for the current user")

    def _get_unix(self, path: str, headers: dict[str, str]) -> Any:
        connection = UnixHTTPConnection(self.resolved_controller, timeout=self.config.timeout)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            payload = response.read()
        finally:
            connection.close()
        if response.status >= 400:
            raise RuntimeError(f"Mihomo API returned HTTP {response.status} for {path}")
        return json.loads(payload.decode("utf-8"))

    def _get_http(self, path: str, headers: dict[str, str]) -> Any:
        parsed = urlparse(self.config.controller)
        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port
        base_path = parsed.path.rstrip("/")
        request_path = f"{base_path}{path}" if base_path else path

        connection = connection_cls(host, port=port, timeout=self.config.timeout)
        try:
            connection.request("GET", request_path, headers=headers)
            response = connection.getresponse()
            payload = response.read()
        finally:
            connection.close()
        if response.status >= 400:
            raise RuntimeError(f"Mihomo API returned HTTP {response.status} for {path}")
        return json.loads(payload.decode("utf-8"))

    def version(self) -> Any:
        return self.get_json("/version")

    def raw_connections(self) -> dict[str, Any]:
        payload = self.get_json("/connections")
        if isinstance(payload, dict):
            return payload
        return {"connections": payload}

    def connection_snapshots(
        self,
        process_lookup: ProcessLookup | None = None,
        process_lookup_factory: Callable[[], ProcessLookup] | None = None,
    ) -> list[ConnectionSnapshot]:
        payload = self.raw_connections()
        up, down = payload.get("uploadTotal"), payload.get("downloadTotal")
        self.last_totals = (up, down) if isinstance(up, int) and isinstance(down, int) else None
        items = [item for item in (payload.get("connections") or []) if isinstance(item, dict)]
        if (
            process_lookup is None
            and process_lookup_factory is not None
            and needs_process_lookup(items)
        ):
            process_lookup = process_lookup_factory()
        return [
            ConnectionSnapshot.from_api_item(item, process_lookup=process_lookup)
            for item in items
        ]
