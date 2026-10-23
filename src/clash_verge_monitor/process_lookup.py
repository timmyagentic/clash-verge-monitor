from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


CORE_PROCESS_MARKERS = (
    "verge-mihomo",
    "mihomo",
    "clash-verge",
    "clash verge",
    "clash-meta",
)


def lsof_path() -> str | None:
    discovered = shutil.which("lsof")
    if discovered:
        return discovered
    fallback = Path("/usr/sbin/lsof")
    return str(fallback) if fallback.is_file() else None


def parse_lsof_process_names(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        if line.startswith("c") and len(line) > 1:
            name = line[1:].strip()
            if name:
                names.append(name)
    return names


def _is_proxy_core(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in CORE_PROCESS_MARKERS)


def choose_process_name(names: list[str]) -> str | None:
    for name in names:
        if name and not _is_proxy_core(name):
            return name
    return None


@dataclass(frozen=True)
class SocketOwner:
    process: str
    protocol: str
    local_address: str
    local_port: int


def _parse_local_endpoint(value: str) -> tuple[str, int] | None:
    endpoint = value.split("->", 1)[0].strip()
    if endpoint.startswith("["):
        closing = endpoint.find("]")
        if closing < 0 or closing + 1 >= len(endpoint) or endpoint[closing + 1] != ":":
            return None
        address = endpoint[1:closing]
        port_text = endpoint[closing + 2 :]
    else:
        if ":" not in endpoint:
            return None
        address, port_text = endpoint.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError:
        return None
    return address or "*", port


def parse_lsof_socket_owners(output: str) -> list[SocketOwner]:
    owners: list[SocketOwner] = []
    process = ""
    protocol = ""
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            process = ""
            protocol = ""
        elif field == "c":
            process = value.strip()
        elif field == "f":
            protocol = ""
        elif field == "P":
            protocol = value.strip().lower()
        elif field == "n" and process and protocol in {"tcp", "udp"}:
            endpoint = _parse_local_endpoint(value)
            if endpoint is not None:
                owners.append(
                    SocketOwner(
                        process=process,
                        protocol=protocol,
                        local_address=endpoint[0],
                        local_port=endpoint[1],
                    )
                )
    return owners


class ProcessTable:
    def __init__(self, owners: list[SocketOwner] | None = None) -> None:
        self.owners = list(owners or [])

    def lookup(self, source_ip: str, source_port: int, network: str) -> str | None:
        protocol = network.strip().lower()
        candidates = [
            owner
            for owner in self.owners
            if owner.protocol == protocol
            and owner.local_port == source_port
            and not _is_proxy_core(owner.process)
        ]
        if not candidates:
            return None

        exact_names = list(
            dict.fromkeys(owner.process for owner in candidates if owner.local_address == source_ip)
        )
        if len(exact_names) == 1:
            return exact_names[0]
        if len(exact_names) > 1:
            return None

        # TUN reports a virtual source address (commonly 198.18.0.1), while
        # lsof sees the application's actual local socket. Protocol + local
        # port is safe only when it identifies one non-core process.
        fallback_names = list(dict.fromkeys(owner.process for owner in candidates))
        return fallback_names[0] if len(fallback_names) == 1 else None


Runner = Callable[..., subprocess.CompletedProcess[str]]


def capture_process_table(
    timeout: float = 2.0,
    *,
    runner: Runner = subprocess.run,
) -> ProcessTable:
    executable = lsof_path()
    if not executable:
        return ProcessTable()
    try:
        result = runner(
            [executable, "-nP", "-iTCP", "-iUDP", "-FpcPn"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ProcessTable()
    if result.returncode not in (0, 1):
        return ProcessTable()
    return ProcessTable(parse_lsof_socket_owners(result.stdout))


def capture_process_lookup(
    timeout: float = 2.0,
) -> Callable[[str, int, str], str | None]:
    return capture_process_table(timeout=timeout).lookup


def lookup_process_name(
    source_ip: str | int,
    source_port: int | None = None,
    network: str = "tcp",
    timeout: float = 2.0,
) -> str | None:
    """Resolve one endpoint; retained as a compatibility helper.

    Sampler and health paths use ``capture_process_lookup`` so lsof runs only
    once per controller snapshot.
    """
    if isinstance(source_ip, int):
        source_port = source_ip
        source_ip = ""
    if not source_port:
        return None
    return capture_process_table(timeout=timeout).lookup(source_ip, source_port, network)
