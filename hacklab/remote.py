"""Remote-view policy (owner's P5 notes): who is asking, and whether a remote
viewer is allowed to change anything right now.

Source is the peer address: Tailscale's ranges are "remote", everything else
(home LAN, the setup hotspot, localhost) is "local". The helping switch can be
turned on only by a remote peer and switches itself off after two hours.
"""

from __future__ import annotations

import json
import time
from ipaddress import ip_address, ip_network
from pathlib import Path

TAILSCALE = (ip_network("100.64.0.0/10"), ip_network("fd7a:115c:a1e0::/48"))
HELPING_HOURS = 2.0
TRUST_SOURCE_HEADER = False  # tests only: lets X-Hacklab-Source pick the source
clock = time.time  # patched in tests

MSG_REMOTE_VIEW = "Remote view only. Turn on helping to make changes."
MSG_NO_SWITCH = "That switch only exists for remote helpers."


def classify(addr: str | None) -> str:
    try:
        ip = ip_address(addr or "")
    except ValueError:
        return "local"
    return "remote" if any(ip in net for net in TAILSCALE) else "local"


def source_of(request, allow_header: bool = False) -> str:
    """'remote' or 'local' for a Starlette request."""
    if (allow_header or TRUST_SOURCE_HEADER) and request.headers.get("x-hacklab-source") in (
        "remote",
        "local",
    ):
        return request.headers["x-hacklab-source"]
    return classify(request.client.host if request.client else None)


class Helping:
    """Server-wide 'a remote helper may change things' switch with auto-off."""

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)
        self._until = 0.0

    def is_on(self) -> bool:
        return clock() < self._until

    def set(self, on: bool, peer: str | None) -> bool:
        self._until = clock() + HELPING_HOURS * 3600 if on else 0.0
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({"ts": int(clock()), "on": on, "peer": peer}) + "\n")
        return self.is_on()
