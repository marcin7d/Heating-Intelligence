"""Read-only Heating Intelligence integration."""
from homeassistant.const import Platform

from .coordinator import HeatingCoordinator


async def async_setup_entry(hass, entry):
    coordinator = HeatingCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
