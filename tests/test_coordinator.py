import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.daikinone.client.client import DaikinOne
from custom_components.daikinone.client.models import DaikinUserCredentials
from custom_components.daikinone.coordinator import DaikinOneCoordinator
from custom_components.daikinone.exceptions import DaikinAuthException, DaikinServiceException
from tests.test_mapping import AIR_HANDLER_DATA, _make_device


def _coordinator(daikin: DaikinOne) -> DaikinOneCoordinator:
    entry = SimpleNamespace(async_on_unload=MagicMock(), title="Daikin One", pref_disable_polling=False)
    return DaikinOneCoordinator(MagicMock(), entry, daikin)  # type: ignore[arg-type]


@pytest.fixture
def daikin() -> DaikinOne:
    return DaikinOne(DaikinUserCredentials(email="test@example.com", password="password"))


class TestUpdateData:
    async def test_returns_thermostats_from_a_fresh_fetch(self, daikin: DaikinOne) -> None:
        with patch.object(daikin._transport, "request", new=AsyncMock(return_value=[_make_device(AIR_HANDLER_DATA)])):
            result = await _coordinator(daikin)._async_update_data()

        assert list(result) == ["device123"]

    async def test_rejected_credentials_raise_config_entry_auth_failed(self, daikin: DaikinOne) -> None:
        """The coordinator turns ConfigEntryAuthFailed into a reauth prompt for the user."""
        with patch.object(daikin, "update", new=AsyncMock(side_effect=DaikinAuthException("nope"))):
            with pytest.raises(ConfigEntryAuthFailed):
                await _coordinator(daikin)._async_update_data()

    async def test_service_errors_raise_update_failed(self, daikin: DaikinOne) -> None:
        """UpdateFailed marks every entity unavailable until the next successful poll."""
        with patch.object(daikin, "update", new=AsyncMock(side_effect=DaikinServiceException("503", status=503))):
            with pytest.raises(UpdateFailed):
                await _coordinator(daikin)._async_update_data()

    async def test_a_hung_fetch_times_out(self, daikin: DaikinOne) -> None:
        """A request that never answers must not stall polling; it fails and the next poll runs."""

        async def hang() -> None:
            await asyncio.sleep(3600)

        with (
            patch("custom_components.daikinone.coordinator.UPDATE_TIMEOUT_SECONDS", 0.01),
            patch.object(daikin, "update", new=hang),
        ):
            with pytest.raises(UpdateFailed):
                await _coordinator(daikin)._async_update_data()


class TestClientCache:
    def test_thermostat_cache_is_per_client(self) -> None:
        """Regression test: the cache was a class attribute shared by every DaikinOne instance,
        so a reloaded integration (or the config flow's throwaway client) saw stale devices."""
        a = DaikinOne(DaikinUserCredentials(email="a@example.com", password="x"))
        b = DaikinOne(DaikinUserCredentials(email="b@example.com", password="x"))
        a._DaikinOne__thermostats["t1"] = MagicMock()  # type: ignore[attr-defined]

        assert b.get_thermostats() == {}
