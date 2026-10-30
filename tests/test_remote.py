"""Source classification: Tailscale peers are 'remote', everything else 'local'."""

import pytest

from hacklab.remote import classify


@pytest.mark.parametrize(
    "addr, expected",
    [
        ("100.71.59.115", "remote"),  # Tailscale CGNAT range 100.64.0.0/10
        ("100.127.255.254", "remote"),
        ("fd7a:115c:a1e0::d401:fbf1", "remote"),  # Tailscale IPv6
        ("100.128.0.1", "local"),  # outside the /10
        ("10.0.0.4", "local"),  # home LAN
        ("10.41.0.113", "local"),  # setup hotspot
        ("127.0.0.1", "local"),
        ("192.168.1.20", "local"),
        ("testclient", "local"),  # Starlette's TestClient host
        (None, "local"),
    ],
)
def test_classify(addr, expected):
    assert classify(addr) == expected
