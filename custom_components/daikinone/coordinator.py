"""Single polling loop shared by every Daikin One entity."""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from custom_components.daikinone.client.client import DaikinOne
from custom_components.daikinone.client.models import DaikinThermostat
from custom_components.daikinone.const import DOMAIN, UPDATE_INTERVAL
from custom_components.daikinone.exceptions import DaikinAuthException, DaikinServiceException

log = logging.getLogger(__name__)

# Upper bound on one poll, login included. Without it a request that never answers holds the
# poll open and every entity keeps showing its last value.
UPDATE_TIMEOUT_SECONDS = 60

type DaikinThermostats = dict[str, DaikinThermostat]


class DaikinOneCoordinator(DataUpdateCoordinator[DaikinThermostats]):
    """Fetches all thermostats from the Daikin cloud once per interval for every entity.

    A failed, timed-out, or cancelled fetch marks every entity unavailable until the next
    successful one, and polling always continues.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, daikin: DaikinOne) -> None:
        super().__init__(hass, log, name=DOMAIN, config_entry=entry, update_interval=UPDATE_INTERVAL)
        self.daikin = daikin

    async def _async_update_data(self) -> DaikinThermostats:
        try:
            async with asyncio.timeout(UPDATE_TIMEOUT_SECONDS):
                await self.daikin.update()
        except DaikinAuthException as e:
            raise ConfigEntryAuthFailed(f"Daikin cloud rejected the stored credentials: {e}") from e
        except DaikinServiceException as e:
            raise UpdateFailed(f"Daikin cloud request failed: {e}") from e
        except TimeoutError as e:
            raise UpdateFailed(f"Daikin cloud did not answer within {UPDATE_TIMEOUT_SECONDS}s") from e

        return self.daikin.get_thermostats()
