"""Config flow for E.ON Drive."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import create_client
from .api import EonDriveAuthError, EonDriveClient, EonDriveError
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DEVICE_ID,
    CONF_LOCATIONS,
    CONF_QUERY,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import tracked_location_ids

_LOGGER = logging.getLogger(__name__)

_PASSWORD = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
_EMAIL = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): _EMAIL,
        vol.Required(CONF_PASSWORD): _PASSWORD,
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_CLIENT_SECRET): _PASSWORD,
    }
)


def _location_options(results: list[dict[str, Any]]) -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(value=str(item["id"]), label=str(item.get("name") or item["id"]).strip())
        for item in results
        if isinstance(item, dict) and item.get("id") is not None
    ]


def _multi_select(options: list[selector.SelectOptionDict]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, multiple=True, mode=selector.SelectSelectorMode.LIST
        )
    )


async def _try_login(client: EonDriveClient) -> str | None:
    """Return an error key, or None when login works."""
    try:
        await client.login()
    except EonDriveAuthError:
        return "invalid_auth"
    except EonDriveError:
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error during E.ON Drive login")
        return "unknown"
    return None


class EonDriveConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._client: EonDriveClient | None = None
        self._results: list[selector.SelectOptionDict] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EonDriveOptionsFlow:
        return EonDriveOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            data = {
                **user_input,
                CONF_USERNAME: username,
                CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
                CONF_DEVICE_ID: str(uuid.uuid4()).upper(),
            }
            client = create_client(self.hass, data)
            error = await _try_login(client)
            if error is None:
                self._data = data
                self._client = client
                return await self.async_step_search()
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            query = (user_input.get(CONF_QUERY) or "").strip()
            if not query:
                return self._create([])
            assert self._client is not None
            try:
                self._results = _location_options(await self._client.search_locations(query))
            except EonDriveError:
                errors["base"] = "cannot_connect"
            else:
                if self._results:
                    return await self.async_step_select()
                errors["base"] = "no_results"
        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema({vol.Optional(CONF_QUERY): str}),
            errors=errors,
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._create(user_input.get(CONF_LOCATIONS, []))
        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema(
                {vol.Required(CONF_LOCATIONS, default=[]): _multi_select(self._results)}
            ),
        )

    def _create(self, locations: list[str]) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._data[CONF_USERNAME],
            data=self._data,
            options={
                CONF_LOCATIONS: [str(i) for i in locations],
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            error = await _try_login(create_client(self.hass, data))
            if error is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )


class EonDriveOptionsFlow(OptionsFlow):
    """Change tracked locations and the polling interval."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._results: list[selector.SelectOptionDict] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        coordinator = getattr(self.config_entry, "runtime_data", None)
        current = tracked_location_ids(self.config_entry)
        names = {
            loc_id: loc.name
            for loc_id, loc in (coordinator.data.locations.items() if coordinator else [])
        }
        if user_input is not None:
            self._options = {
                CONF_LOCATIONS: [str(i) for i in user_input.get(CONF_LOCATIONS, [])],
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
            }
            query = (user_input.get(CONF_QUERY) or "").strip()
            if not query:
                return self.async_create_entry(data=self._options)
            if coordinator is None:
                errors["base"] = "cannot_connect"
            else:
                try:
                    found = _location_options(
                        await coordinator.client.search_locations(query)
                    )
                except EonDriveError:
                    errors["base"] = "cannot_connect"
                else:
                    kept = set(self._options[CONF_LOCATIONS])
                    self._results = [o for o in found if o["value"] not in kept]
                    if self._results:
                        return await self.async_step_add()
                    errors["base"] = "no_results"

        fields: dict[Any, Any] = {}
        if current:
            fields[vol.Optional(CONF_LOCATIONS, default=current)] = _multi_select(
                [
                    selector.SelectOptionDict(value=i, label=names.get(i, f"#{i}"))
                    for i in current
                ]
            )
        fields[vol.Optional(CONF_QUERY)] = str
        fields[
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=self.config_entry.options.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL,
                max=MAX_SCAN_INTERVAL,
                step=30,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            )
        )
        schema = vol.Schema(fields)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def async_step_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            added = [str(i) for i in user_input.get(CONF_LOCATIONS, [])]
            self._options[CONF_LOCATIONS] = list(
                dict.fromkeys([*self._options[CONF_LOCATIONS], *added])
            )
            return self.async_create_entry(data=self._options)
        return self.async_show_form(
            step_id="add",
            data_schema=vol.Schema(
                {vol.Required(CONF_LOCATIONS, default=[]): _multi_select(self._results)}
            ),
        )
