from __future__ import annotations

import http.client
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .models import ConnectionSnapshot, ProcessLookup


DEFAULT_UNIX_SOCKET = "/tmp/verge/verge-mihomo.sock"


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


@dataclass(frozen=True)
class ControllerConfig:
    controller: str = DEFAULT_UNIX_SOCKET
    secret: str | None = None
    timeout: float = 5.0

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

    def get_json(self, path: str) -> Any:
        if not path.startswith("/"):
            path = f"/{path}"
        headers = {"Host": "localhost"}
        if self.config.secret:
            headers["Authorization"] = f"Bearer {self.config.secret}"

        if self.config.is_http:
            return self._get_http(path, headers)
        return self._get_unix(path, headers)

    def _get_unix(self, path: str, headers: dict[str, str]) -> Any:
        connection = UnixHTTPConnection(self.config.socket_path, timeout=self.config.timeout)
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
    ) -> list[ConnectionSnapshot]:
        payload = self.raw_connections()
        items = payload.get("connections") or []
        return [
            ConnectionSnapshot.from_api_item(item, process_lookup=process_lookup)
            for item in items
            if isinstance(item, dict)
        ]

