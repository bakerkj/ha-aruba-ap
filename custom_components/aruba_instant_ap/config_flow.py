# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Config flow for Aruba Instant AP integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CLIENTS_MAPPED_ONLY,
    CONF_COMMUNITY,
    CONF_HOST,
    CONF_MAC_HOSTNAME_FILE,
    CONF_SNMP_PORT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_SNMP_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    OID_SYS_NAME,
)
from .snmp_helper import async_snmp_get

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_COMMUNITY, default="public"): str,
        vol.Required(CONF_SNMP_PORT, default=DEFAULT_SNMP_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required("snmp_version", default="v2c"): vol.In(["v2c", "v1"]),
        vol.Required(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=10)
        ),
        vol.Optional(CONF_MAC_HOSTNAME_FILE, default=""): str,
        vol.Optional(CONF_CLIENTS_MAPPED_ONLY, default=False): bool,
    }
)


class ArubaInstantAPConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Config flow for Aruba Instant AP."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST].lower())
            self._abort_if_unique_id_configured()

            try:
                await _test_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_COMMUNITY],
                    user_input[CONF_SNMP_PORT],
                )
            except ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during connection test")
                errors["base"] = "unknown"

            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_HOST],
                    data=_connection_data(user_input),
                    options={
                        "snmp_version": user_input.get("snmp_version", "v2c"),
                        CONF_UPDATE_INTERVAL: user_input.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                        CONF_MAC_HOSTNAME_FILE: user_input.get(
                            CONF_MAC_HOSTNAME_FILE, ""
                        ),
                        CONF_CLIENTS_MAPPED_ONLY: user_input.get(
                            CONF_CLIENTS_MAPPED_ONLY, False
                        ),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow updating all settings without re-adding."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                await _test_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_COMMUNITY],
                    user_input[CONF_SNMP_PORT],
                )
            except ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reconfigure")
                errors["base"] = "unknown"

            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    title=user_input[CONF_HOST],
                    data_updates=_connection_data(user_input),
                    options={
                        "snmp_version": user_input.get("snmp_version", "v2c"),
                        CONF_UPDATE_INTERVAL: user_input.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                        CONF_MAC_HOSTNAME_FILE: user_input.get(
                            CONF_MAC_HOSTNAME_FILE, ""
                        ),
                        CONF_CLIENTS_MAPPED_ONLY: user_input.get(
                            CONF_CLIENTS_MAPPED_ONLY, False
                        ),
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str,
                    vol.Required(
                        CONF_COMMUNITY,
                        default=entry.data.get(CONF_COMMUNITY, "public"),
                    ): str,
                    vol.Required(
                        CONF_SNMP_PORT,
                        default=entry.data.get(CONF_SNMP_PORT, DEFAULT_SNMP_PORT),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                    vol.Required(
                        "snmp_version",
                        default=entry.options.get("snmp_version", "v2c"),
                    ): vol.In(["v2c", "v1"]),
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10)),
                    vol.Optional(
                        CONF_MAC_HOSTNAME_FILE,
                        default=entry.options.get(CONF_MAC_HOSTNAME_FILE, ""),
                    ): str,
                    vol.Optional(
                        CONF_CLIENTS_MAPPED_ONLY,
                        default=entry.options.get(CONF_CLIENTS_MAPPED_ONLY, False),
                    ): bool,
                }
            ),
            errors=errors,
        )


def _connection_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Extract connection fields from user input."""
    return {
        CONF_HOST: user_input[CONF_HOST],
        CONF_COMMUNITY: user_input[CONF_COMMUNITY],
        CONF_SNMP_PORT: user_input[CONF_SNMP_PORT],
    }


async def _test_connection(host: str, community: str, snmp_port: int) -> None:
    """Test SNMP connectivity by fetching sysName. Raises ConnectionError if unreachable."""
    result = await async_snmp_get(
        host,
        community,
        snmp_port,
        OID_SYS_NAME,
        timeout=12,
        retries=3,
    )
    if result is None:
        raise ConnectionError(f"No SNMP response from {host}:{snmp_port}")
