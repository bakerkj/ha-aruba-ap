# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for snmp_helper's error-handling surface.

The narrowed `except (OSError, TimeoutError, SnmpError)` in
`async_snmp_get` / `async_snmp_walk` replaced a blind `except Exception`.
These tests document the three error classes the module is expected to
swallow (returning None / {}) and ensure they stay caught.
"""

from unittest.mock import patch

import pytest
from puresnmp.exc import SnmpError, Timeout

from custom_components.aruba_instant_ap.snmp_helper import (
    async_snmp_get,
    async_snmp_walk,
)

_HOST = "192.0.2.1"
_COMMUNITY = "public"
_PORT = 161
_OID = "1.3.6.1.2.1.1.1.0"


@pytest.mark.parametrize(
    "exc",
    [
        OSError("network unreachable"),
        TimeoutError("socket timeout"),
        Timeout("SNMP request timed out"),
        SnmpError("protocol error"),
    ],
)
async def test_async_snmp_get_swallows_expected_errors(exc):
    with patch(
        "custom_components.aruba_instant_ap.snmp_helper.Client",
        side_effect=exc,
    ):
        result = await async_snmp_get(_HOST, _COMMUNITY, _PORT, _OID)
    assert result is None


@pytest.mark.parametrize(
    "exc",
    [
        OSError("network unreachable"),
        TimeoutError("socket timeout"),
        Timeout("SNMP request timed out"),
        SnmpError("protocol error"),
    ],
)
async def test_async_snmp_walk_swallows_expected_errors(exc):
    with patch(
        "custom_components.aruba_instant_ap.snmp_helper.Client",
        side_effect=exc,
    ):
        result = await async_snmp_walk(_HOST, _COMMUNITY, _PORT, _OID)
    assert result == {}
