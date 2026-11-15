"""Default-off application networking, independent of model prices or budgets."""

import ipaddress
import os
import sys


class OfflineModeError(RuntimeError):
    pass


def offline_enabled():
    # Only one explicit value enables external networking. Typos fail closed.
    return os.getenv("PAPER_NETWORK_MODE", "offline").strip().lower() != "online"


def require_online(operation):
    if offline_enabled():
        raise OfflineModeError(
            "Offline mode blocks "
            + operation
            + ". Set PAPER_NETWORK_MODE=online only for an authorised run."
        )


def _loopback(host):
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def _audit(event, args):
    if not offline_enabled():
        return
    if event in {
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
    } and not _loopback(args[0]):
        raise OfflineModeError("Offline mode blocks external name resolution.")
    if event in {"socket.connect", "socket.sendto"}:
        address = args[1]
        # Unix-domain IPC is local; TCP permits only literal loopback addresses.
        if isinstance(address, tuple) and not _loopback(address[0]):
            raise OfflineModeError("Offline mode blocks external connections.")


sys.addaudithook(_audit)
