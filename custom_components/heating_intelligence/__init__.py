"""Heating Intelligence: read-only predictive heating diagnostics."""
from homeassistant.const import Platform
from .coordinator import HeatingCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_migrate_entry(hass, entry):
    """Upgrade existing 0.1.x config entries without deleting user-selected zones.

    The 0.2.x coordinator handles missing optional sources and zone profiles.
    """
    if entry.version == 1:
        data = dict(entry.data)
        data.setdefault("orientations", {})
        data.setdefault("profiles", {})
        hass.config_entries.async_update_entry(entry, data=data, version=2)
        return True
    return entry.version == 2

async def async_setup_entry(hass, entry):
    coordinator = HeatingCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
