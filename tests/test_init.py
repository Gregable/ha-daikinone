from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.daikinone import async_setup_entry
from custom_components.daikinone.const import DOMAIN


def _entry() -> SimpleNamespace:
    return SimpleNamespace(data={CONF_EMAIL: "test@example.com", CONF_PASSWORD: "password"})


def _hass() -> SimpleNamespace:
    return SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
    )


class TestAsyncSetupEntry:
    @pytest.mark.parametrize("error", [ConfigEntryNotReady("cloud down"), ConfigEntryAuthFailed("bad password")])
    async def test_first_refresh_failure_propagates(self, error: Exception) -> None:
        """The coordinator's first refresh raises ConfigEntryNotReady (HA retries setup) or
        ConfigEntryAuthFailed (HA asks the user to re-authenticate); setup must not swallow either."""
        hass = _hass()

        with patch("custom_components.daikinone.DaikinOneCoordinator") as coordinator_cls:
            coordinator_cls.return_value.async_config_entry_first_refresh = AsyncMock(side_effect=error)

            with pytest.raises(type(error)):
                await async_setup_entry(hass, _entry())  # type: ignore[arg-type]

        assert DOMAIN not in hass.data
        hass.config_entries.async_forward_entry_setups.assert_not_called()

    async def test_successful_setup_stores_data_and_loads_platforms(self) -> None:
        hass = _hass()
        entry = _entry()

        with patch("custom_components.daikinone.DaikinOneCoordinator") as coordinator_cls:
            coordinator = MagicMock(async_config_entry_first_refresh=AsyncMock())
            coordinator_cls.return_value = coordinator

            assert await async_setup_entry(hass, entry) is True  # type: ignore[arg-type]

        assert hass.data[DOMAIN].coordinator is coordinator
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()
