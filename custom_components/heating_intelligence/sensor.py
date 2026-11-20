"""Read-only sensors, including model learning diagnostics and solar exposure."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity

SYSTEM = [
    ('delta_t', 'Supply–return ΔT', 'K'),
    ('starts', 'Boiler starts today', None),
    ('runtime', 'Boiler runtime today', 'min'),
    ('cycle', 'Mean boiler cycle', 'min'),
    ('coverage', 'Boiler history coverage', '%'),
    ('history', 'Recorder history', None),
    ('demand', 'Heat demand index', None),
    ('advice', 'Boiler advice', None),
    ('boiler_simulation_status', 'Boiler forecast status', None),
    ('boiler_demand_zones', 'Zones requesting heat now', None),
    ('boiler_start_pending_minutes', 'Boiler start demand duration', 'min'),
    ('boiler_forecast_30', 'Boiler state in 30 min', None),
    ('boiler_forecast_60', 'Boiler state in 60 min', None),
    ('boiler_forecast_120', 'Boiler state in 120 min', None),
    ('boiler_forecast_360', 'Boiler state in 360 min', None),
    ('boiler_demand_30', 'Zones requesting heat in 30 min', None),
    ('boiler_demand_60', 'Zones requesting heat in 60 min', None),
    ('boiler_demand_120', 'Zones requesting heat in 120 min', None),
    ('boiler_demand_360', 'Zones requesting heat in 360 min', None),
]
ZONE = [
    ('t_30', 'Temperature in 30 min', '°C'),
    ('t_60', 'Temperature in 60 min', '°C'),
    ('t_120', 'Temperature in 120 min', '°C'),
    ('t_360', 'Temperature in 360 min', '°C'),
    ('lead', 'Recommended preheat lead', 'min'),
    ('model_status', 'Model training status', None),
    ('model_samples', 'Model usable pairs', None),
    ('model_last_training', 'Last model training attempt (Unix UTC)', None),
    ('model_raw_rows', 'Model total history rows', None),
    ('model_valid_rows', 'Model valid history rows', None),
    ('model_missing_room', 'Model missing room temperature rows', None),
    ('model_missing_outdoor', 'Model missing outdoor temperature rows', None),
    ('model_missing_heat', 'Model missing heat signal rows', None),
    ('model_heating_samples', 'Model heating samples', None),
    ('model_idle_samples', 'Model idle samples', None),
    ('model_temperature_changes', 'Model temperature changes', None),
    ('model_candidate_mae', 'Model candidate validation MAE', 'K'),
    ('model_persistence_mae', 'Model constant-temperature baseline MAE', 'K'),
    ('model_horizons', 'Validated forecast horizons', None),
    ('model_mae_30', 'Model validation MAE 30 min', 'K'),
    ('model_baseline_30', 'Constant-temperature MAE 30 min', 'K'),
    ('model_mae_60', 'Model validation MAE 60 min', 'K'),
    ('model_baseline_60', 'Constant-temperature MAE 60 min', 'K'),
    ('model_mae_120', 'Model validation MAE 120 min', 'K'),
    ('model_baseline_120', 'Constant-temperature MAE 120 min', 'K'),
    ('model_mae_360', 'Model validation MAE 360 min', 'K'),
    ('model_baseline_360', 'Constant-temperature MAE 360 min', 'K'),
    ('model_candidate_heating_gain', 'Candidate heating gain', None),
    ('model_zero_gain_candidates', 'Candidates with zero heating gain', None),
    ('model_evaluated_candidates', 'Candidates evaluated for long-horizon validation', None),
    ('model_error', 'Model validation MAE (5 min)', 'K'),
    ('model_memory', 'Thermal memory coefficient', None),
    ('solar_gain_index', 'Solar exposure index', None),
    ('solar_gain_coefficient', 'Solar gain coefficient', None),
    ('solar_data_source', 'Solar data source', None),
    ('solar_model_active', 'Solar model active', None),
    ('room_profile', 'Room profile', None),
    ('kitchen_internal_heat', 'Kitchen internal heat', None),
    ('kitchen_heat_source', 'Kitchen heat source', None),
    ('kitchen_excluded_samples', 'Kitchen training samples excluded', None),
    ('kitchen_heat_events', 'Kitchen heat events in training window', None),
]

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [HeatingSensor(coordinator, entry.entry_id, key, label, unit) for key, label, unit in SYSTEM]
    for zone in entry.data['zones']:
        state = hass.states.get(zone)
        name = state.name if state else zone
        entities.extend(HeatingSensor(coordinator, entry.entry_id, key, label, unit, zone, name)
                        for key, label, unit in ZONE)
    async_add_entities(entities)


class HeatingSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id, key, label, unit, zone=None, zone_name=None):
        super().__init__(coordinator)
        self.key, self.zone = key, zone
        device_id = f'{entry_id}_{zone}' if zone else entry_id
        self._attr_unique_id = f'{device_id}_{key}'
        self._attr_device_info = {
            'identifiers': {('heating_intelligence', device_id)},
            'name': zone_name or 'Heating Intelligence',
            'manufacturer': 'Heating Intelligence',
        }
        self._attr_name = label
        self._attr_native_unit_of_measurement = unit
        if key.startswith('t_'):
            self._attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        group = data.get('zones', {}).get(self.zone, {}) if self.zone else data
        value = group.get(self.key)
        if isinstance(value, bool):
            return 'Yes' if value else 'No'
        return value

    @property
    def available(self):
        return super().available and self.native_value is not None
