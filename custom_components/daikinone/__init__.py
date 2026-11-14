import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from custom_components.daikinone.const import (
    CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY,
    PLATFORMS,
    DOMAIN,
)
from custom_components.daikinone.client.client import DaikinOne
from custom_components.daikinone.client.models import DaikinUserCredentials
from custom_components.daikinone.coordinator import DaikinOneCoordinator

log = logging.getLogger(__name__)


@dataclass
class DaikinOneData:
    entry: ConfigEntry
    daikin: DaikinOne
    coordinator: DaikinOneCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the given config entry"""

    log.info(f"Setting up Daikin One integration for {entry.data[CONF_EMAIL]}")

    daikin = DaikinOne(DaikinUserCredentials(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]))
    coordinator = DaikinOneCoordinator(hass, entry, daikin)

    # raises ConfigEntryNotReady (HA retries setup) or ConfigEntryAuthFailed (HA asks the user to
    # re-authenticate) instead of leaving the entry permanently failed until a manual reload
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN] = DaikinOneData(entry, daikin, coordinator)

    # load platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry and platforms"""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.pop(DOMAIN)
    return ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    log.debug("Migrating from version %s.%s", entry.version, entry.minor_version)

    if entry.version > 1:
        log.error(
            "Incompatible downgrade detected, please restore from a earlier backup or remove and re-add the integration",
            entry.version,
            entry.minor_version,
        )
        return False

    if entry.version == 1:
        new = {**entry.data}

        # migrate to 1.2
        if entry.minor_version < 2:
            entry.minor_version = 2

            # retain legacy id schema if this is an upgrade of an existing entry
            new[CONF_OPTION_ENTITY_UID_SCHEMA_VERSION_KEY] = 0

        hass.config_entries.async_update_entry(entry, data=new)

    log.info("Migration to version %s.%s successful", entry.version, entry.minor_version)

    return True
