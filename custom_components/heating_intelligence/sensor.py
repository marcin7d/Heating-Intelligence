"""Expose measurements, model diagnostics and advisory outputs."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .model import HORIZONS

ADVICE = ["insufficient_data", "no_demand", "running", "consider_heat", "recent_start_low_demand", "low_demand"]
SYSTEM = (
    ("delta_t", "Supply–return ΔT", "K"),
    ("starts", "Boiler starts today", None),
    ("runtime", "Boiler runtime today", "min"),
    ("cycle", "Mean completed cycle today", "min"),
    ("coverage", "Boiler history coverage today", "%"),
    ("history", "Recorder history", None),
    ("demand", "Heat demand index", None),
    ("advice", "Boiler advice", None),
)
ZONE = (
    *((f"t_{minute}", f"Temperature in {minute} min", "°C") for minute in HORIZONS),
    ("lead", "Recommended preheat lead time", "min"),
    ("error", "Model 5 min validation MAE", "K"),
    ("memory", "Model thermal memory coefficient", None),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [HeatingSensor(coordinator, entry.entry_id, key, name, unit) for key, name, unit in SYSTEM]
    for zone in entry.data["zones"]:
        state = hass.states.get(zone)
        zone_name = state.name if state else zone
        entities.extend(HeatingSensor(coordinator, entry.entry_id, key, name, unit, zone, zone_name)
                        for key, name, unit in ZONE)
    async_add_entities(entities)


class HeatingSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id, key, name, unit, zone=None, zone_name=None):
        super().__init__(coordinator)
        self.key, self.zone = key, zone
        device_id = f"{entry_id}_{zone}" if zone else entry_id
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={("heating_intelligence", device_id)},
            name=zone_name or "Heating Intelligence",
            manufacturer="Heating Intelligence",
        )
        self._attr_native_unit_of_measurement = unit
        if key == "advice":
            self._attr_translation_key = key
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ADVICE
        else:
            self._attr_name = name
            if key.startswith("t_"):
                self._attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def native_value(self):
        data = self.coordinator.data
        return (data["zones"][self.zone] if self.zone else data).get(self.key)

    @property
    def available(self):
        return super().available and self.native_value is not None
