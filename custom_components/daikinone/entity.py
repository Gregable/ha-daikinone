import logging
import backoff
from typing import Callable, Awaitable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.daikinone import DaikinOneData
from custom_components.daikinone.const import DOMAIN, MANUFACTURER
from custom_components.daikinone.coordinator import DaikinOneCoordinator
from custom_components.daikinone.client.models import DaikinDevice, DaikinEquipment, DaikinThermostat

log = logging.getLogger(__name__)


class DaikinOneEntity[D: DaikinDevice](CoordinatorEntity[DaikinOneCoordinator]):
    """Base entity. State comes from the shared coordinator; entities never poll on their own."""

    _device: D
    _data: DaikinOneData

    _updates_paused: bool = False

    def __init__(self, data: DaikinOneData, device: D):
        super().__init__(data.coordinator)
        self._data = data
        self._device = device
        self._attr_device_info = self.get_device_info()

    def get_device_info(self) -> DeviceInfo | None:
        """Return device information for this sensor."""

        info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self.device_name,
            manufacturer=MANUFACTURER,
            model=self._device.model,
            sw_version=self._device.firmware_version,
        )

        if self.device_parent is not None:
            info["via_device"] = (DOMAIN, self.device_parent)

        return info

    @property
    def device_name(self) -> str:
        """Return the name of the device."""
        match self._device:
            case DaikinThermostat():
                return f"{self._device.name} Thermostat"
            case DaikinEquipment():
                thermostat = self._data.daikin.get_thermostat(self._device.thermostat_id)
                return f"{thermostat.name} {self._device.name}"
            case _:
                raise ValueError("unexpected device type when generating device name")

    @property
    def device_parent(self) -> str | None:
        """Return the name of the device."""
        match self._device:
            case DaikinEquipment():
                thermostat = self._data.daikin.get_thermostat(self._device.thermostat_id)
                return thermostat.id
            case _:
                return None

    def get_device(self) -> D:
        """Look up this entity's device in the client's cache. Raises KeyError if it is missing."""
        raise NotImplementedError("DaikinOneEntity subclass has not implemented get_device")

    def update_entity_attributes(self) -> None:
        """Update the entity attributes. When this is called, the device has already been updated."""
        raise NotImplementedError("DaikinOneEntity subclass has not implemented update_entity_attributes")

    def refresh_from_cache(self) -> None:
        """Reload this entity's device from the client's cache and recompute its attributes."""
        try:
            self._device = self.get_device()
        except KeyError:
            # Backing device missing from the latest fetch (e.g. equipment skipped due to garbage
            # identity strings). Mark unavailable and retain the last-known _device so attributes
            # recover cleanly on the next successful fetch.
            log.debug("Device %s missing from the latest fetch, marking entity unavailable", self._device.id)
            self._attr_available = False
            return

        self._attr_available = True
        self.update_entity_attributes()

    @property
    def available(self) -> bool:
        # CoordinatorEntity only checks the last fetch; also honor this entity's own state
        # (device missing from the payload, or an offline thermostat for the climate entity)
        return self._attr_available and super().available

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.refresh_from_cache()

    @callback
    def _handle_coordinator_update(self) -> None:
        # an optimistic write is waiting for the cloud to confirm it; a poll could carry older data
        if self._updates_paused:
            return
        self.refresh_from_cache()
        self.async_write_ha_state()

    async def update_state_optimistically(
        self,
        operation: Callable[[], Awaitable[None]],
        optimistic_update: Callable[[D], None],
        check: Callable[[D], bool],
    ) -> None:
        """
        Executes the given state update optimistically, then waits for the API to update the state as well. Regularly
        scheduled updates are paused while waiting to avoid overwriting the optimistic update with stale data. On
        success, the latest fetched state is pushed to every entity through the coordinator.
        """
        # pause entity updates
        self._updates_paused = True

        try:
            # execute change operation
            await operation()

            # execute state update optimistically
            optimistic_update(self._device)
            self.update_entity_attributes()
            self.async_write_ha_state()

            # wait for remote state to be updated
            await self._wait_for_updated_value(check)
        finally:
            # resume entity updates, even if the operation above failed, so a single transient
            # error doesn't permanently freeze this entity until the integration is reloaded
            self._updates_paused = False

        # share the freshly fetched state with every entity; this also restarts the poll timer
        self.coordinator.async_set_updated_data(self._data.daikin.get_thermostats())

    @backoff.on_predicate(
        backoff.constant,
        max_time=10,
        on_success=lambda _: log.debug("Finished waiting for updated value"),
        on_giveup=lambda _: log.debug("Gave up waiting for updated value"),
        logger=log.getChild("backoff"),
        backoff_log_level=logging.DEBUG,
        giveup_log_level=logging.DEBUG,
    )
    async def _wait_for_updated_value(self, check: Callable[[D], bool]) -> bool:
        """
        Waits for an updated value from the API. Continually retries until the check passes or max_time has been
        reached.
        """

        # fetch the latest from the api
        await self._data.daikin.update()

        # check if the value has been updated to the expected value
        return check(self.get_device())
