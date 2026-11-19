"""Recorder-based learning, solar features and transparent model diagnostics."""
import logging
from dataclasses import asdict
from datetime import timedelta
from functools import partial
from statistics import median

from homeassistant.components.recorder import get_instance, history
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt

from .model import (HORIZONS, STEP, Model, boiler_cycles, demand, forecast,
                    heating_proxy, numeric, solar_signal, temp, train_with_diagnostics)
from .kitchen import KitchenObservation, mark_disturbances, power_watts, humidity_percent

_LOGGER = logging.getLogger(__name__)


def state_value(state, default='°C', attr=None):
    if state is None or state.state in ('unknown', 'unavailable'):
        return None
    val = state.attributes.get(attr) if attr else state.state
    return temp(val, state.attributes.get('unit_of_measurement', default))


def boiler_value(state):
    if state is None:
        return None
    text = state.state.lower()
    if text in ('on', '1', '1.0', 'true', 'heating', 'running'):
        return True
    if text in ('off', '0', '0.0', 'false', 'idle'):
        return False
    return None


def request(state, current, target):
    if state is None or state.state in ('unknown', 'unavailable'):
        return None
    if state.state == 'off':
        return False
    action = state.attributes.get('hvac_action')
    if action in ('heating', 'preheating'):
        return True
    if action in ('idle', 'off', 'cooling', 'drying', 'fan'):
        return False
    if state.state in ('heat', 'auto', 'heat_cool') and None not in (current, target):
        return target - current >= .3
    return None


def read_numeric(state):
    if state is None or state.state in ('unknown', 'unavailable'):
        return None
    return numeric(state.state)


def power_sensor(state):
    if state is None or state.state in ('unknown', 'unavailable'):
        return None
    return power_watts(state.state, state.attributes.get('unit_of_measurement', 'W'))


def humidity_sensor(state):
    if state is None or state.state in ('unknown', 'unavailable'):
        return None
    return humidity_percent(state.state, state.attributes.get('unit_of_measurement', '%'))


def compute(config, histories, live, now, midnight, trained_models, training, saved_diagnostics=None):
    """Build five-minute samples and expose per-zone diagnostics.

    All functions here are pure relative to Home Assistant state objects.
    """
    stamp = now // STEP * STEP
    saved_diagnostics = saved_diagnostics or {}
    profiles = config.get('profiles', {})
    kitchen_entities = [profile[key] for profile in profiles.values()
                        if profile.get('type') == 'kitchen'
                        for key in ('oven_power', 'hob_power', 'hood', 'kitchen_humidity')
                        if profile.get(key)]
    ids = list(dict.fromkeys([*config['zones'], *kitchen_entities, *(config[key] for key in
        ('outdoor', 'supply', 'return', 'boiler', 'mixed', 'irradiance', 'illuminance', 'pv_power')
        if config.get(key))]))
    sun_id = 'sun.sun'
    if sun_id not in ids:
        ids.append(sun_id)
    events = {key: sorted([(int(s.last_updated.timestamp()), s) for s in histories.get(key, [])]) for key in ids}
    positions = dict.fromkeys(ids, 0)
    current = {}
    kinds = {zone: 'floor' if zone in config.get('floor', ()) else 'radiator' for zone in config['zones']}
    rows = {zone: [] for zone in config['zones']}
    solar_sources = {}
    kitchen_observations = {zone: [] for zone in config['zones']}
    initial = stamp - (7 * 86400 if training else 6 * 3600)
    for point in range(initial, stamp + STEP, STEP):
        if point == stamp:
            states = live
        else:
            for key in ids:
                values = events.get(key, ())
                while positions[key] < len(values) and values[positions[key]][0] <= point:
                    current[key] = values[positions[key]][1]
                    positions[key] += 1
            states = current
        outside = state_value(states.get(config['outdoor']))
        supply = state_value(states.get(config['supply']))
        mixed = state_value(states.get(config.get('mixed')))
        boiler = boiler_value(states.get(config['boiler']))
        sun = states.get(sun_id)
        sun_az = numeric(sun.attributes.get('azimuth')) if sun else None
        sun_el = numeric(sun.attributes.get('elevation')) if sun else None
        irradiance = read_numeric(states.get(config.get('irradiance')))
        lux = read_numeric(states.get(config.get('illuminance')))
        pv = read_numeric(states.get(config.get('pv_power')))
        for zone, kind in kinds.items():
            st = states.get(zone)
            t = state_value(st, attr='current_temperature')
            setpoint = state_value(st, attr='temperature')
            call = request(st, t, setpoint)
            power = heating_proxy(kind, call, boiler, t, supply, mixed)
            orientation = config.get('orientations', {}).get(zone, {})
            solar, source = solar_signal(irradiance, lux, pv, sun_az, sun_el,
                orientation.get('azimuths', []), orientation.get('shading', 0))
            rows[zone].append((point, t, outside, power, solar))
            profile = profiles.get(zone, {})
            if profile.get('type') == 'kitchen':
                oven = power_sensor(states.get(profile.get('oven_power')))
                hob = power_sensor(states.get(profile.get('hob_power')))
                hood = boiler_value(states.get(profile.get('hood')))
                humidity = humidity_sensor(states.get(profile.get('kitchen_humidity')))
                kitchen_observations[zone].append(KitchenObservation(
                    point, t, power, solar, oven, hob, hood, humidity))
            if point == stamp:
                solar_sources[zone] = source

    diagnostics = {}
    kitchen_info = {}
    for zone, kind in kinds.items():
        if profiles.get(zone, {}).get('type') == 'kitchen':
            masked, state, reason, count, kitchen_event_count = mark_disturbances(
                rows[zone], kitchen_observations[zone])
            kitchen_info[zone] = {'state': state, 'reason': reason, 'excluded': count,
                                  'events': kitchen_event_count, 'training_rows': masked}
        else:
            kitchen_info[zone] = {'state': 'not_applicable', 'reason': 'none',
                                  'excluded': 0, 'events': 0, 'training_rows': rows[zone]}
    if training:
        for zone, kind in kinds.items():
            training_rows = kitchen_info[zone]['training_rows']
            candidate, status, metrics = train_with_diagnostics(training_rows[:-1], kind)
            if candidate is not None:
                trained_models[zone] = candidate
            diagnostics[zone] = {
                'status': status if candidate is not None else
                          ('retained_old_model' if zone in trained_models else status),
                'samples': candidate.samples if candidate else metrics['usable_pairs'],
                **metrics,
                'last_training': now,
                'kitchen_excluded_samples': kitchen_info[zone]['excluded'],
                'kitchen_heat_events': kitchen_info[zone]['events'],
            }

    result = {'zones': {}, 'history': 'available' if any(histories.values()) else 'missing'}
    boiler = boiler_value(live.get(config['boiler']))
    supply = state_value(live.get(config['supply']))
    return_t = state_value(live.get(config['return']))
    result['delta_t'] = round(supply - return_t, 2) if None not in (supply, return_t) else None
    all_boiler_events = [(t, boiler_value(st)) for t, st in events[config['boiler']] if t <= now]
    result.update(boiler_cycles(all_boiler_events, midnight, now))
    demand_rows = []
    for zone, kind in kinds.items():
        points = rows[zone]
        _, room, outside, power, solar = points[-1]
        st = live.get(zone)
        target = state_value(st, attr='temperature')
        call = request(st, room, target)
        demand_rows.append((call, target - room if None not in (target, room) else None))
        active_power = 1.0 if kind == 'floor' and not config.get('mixed') else heating_proxy(
            kind, True, True, room, supply, state_value(live.get(config.get('mixed'))))
        recent = [p[3] for p in points[-144:-1] if p[3] is not None and p[3] > .25]
        if recent and not (kind == 'floor' and not config.get('mixed')):
            active_power = median(recent)
        model = trained_models.get(zone)
        predictions, lead = forecast(model, points, outside, power, solar, target, active_power)
        diag = diagnostics.get(zone, saved_diagnostics.get(zone, {
            'status': 'ready' if model else 'not_trained',
            'samples': model.samples if model else 0,
        }))
        internal = kitchen_info[zone]
        if internal['state'] in ('active', 'cooldown'):
            # The model does not predict residual appliance/cooking heat.
            # Keep a learned model but withhold unreliable live predictions.
            predictions, lead = {}, None
        result['zones'][zone] = {
            **{f't_{h}': predictions.get(h) for h in HORIZONS},
            'lead': lead,
            'model_status': diag['status'],
            '_training_status': diag['status'],
            'model_samples': diag['samples'],
            'model_last_training': diag.get('last_training'),
            'model_raw_rows': diag.get('raw_rows'),
            'model_valid_rows': diag.get('valid_rows'),
            'model_missing_room': diag.get('missing_room'),
            'model_missing_outdoor': diag.get('missing_outdoor'),
            'model_missing_heat': diag.get('missing_heat'),
            'model_heating_samples': diag.get('training_heating_pairs'),
            'model_idle_samples': diag.get('training_idle_pairs'),
            'model_temperature_changes': diag.get('temperature_changes'),
            'model_candidate_mae': diag.get('candidate_mae'),
            'model_persistence_mae': diag.get('persistence_mae'),
            'model_error': round(model.error, 4) if model else None,
            'model_memory': model.memory if model else None,
            'solar_gain_index': solar,
            'solar_gain_coefficient': round(model.solar_gain, 5) if model and model.uses_solar else None,
            'solar_data_source': solar_sources.get(zone, 'missing'),
            'solar_model_active': bool(model and model.uses_solar),
            'room_profile': profiles.get(zone, {}).get('type', 'standard'),
            'kitchen_internal_heat': internal['state'],
            'kitchen_heat_source': internal['reason'],
            'kitchen_excluded_samples': diag.get('kitchen_excluded_samples', 0),
            'kitchen_heat_events': diag.get('kitchen_heat_events', 0),
        }
        if internal['state'] in ('active', 'cooldown'):
            result['zones'][zone]['model_status'] = 'kitchen_heat_event'
        elif model and not predictions:
            result['zones'][zone]['model_status'] = 'missing_recent_data'
    result['demand'], result['advice'] = demand(demand_rows, boiler)
    return result, trained_models


class HeatingModelStore(Store):
    """Discard incompatible 0.1.x model coefficients while preserving config entries.

    Previously saved models have no solar_gain/uses_solar coefficients. They
    must be relearned with the 0.2.x data features rather than reinterpreted.
    """

    async def _async_migrate_func(self, old_major_version, old_minor_version, old_data):
        if old_major_version == 1:
            return {
                'config': old_data.get('config'),
                'models': {},
                'last_training': 0,
                'diagnostics': {},
            }
        raise NotImplementedError(f'Unsupported model storage version {old_major_version}')


class HeatingCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, config_entry=entry, name='heating_intelligence',
                         update_interval=timedelta(minutes=5))
        self.entry = entry
        self.config = dict(entry.data)
        self.store = HeatingModelStore(hass, 2, f'heating_intelligence.{entry.entry_id}')
        self.models = {}
        self.last_training = 0
        self.saved_diagnostics = {}

    async def _async_setup(self):
        saved = await self.store.async_load() or {}
        if saved.get('config') == self.config:
            for zone, raw in saved.get('models', {}).items():
                try:
                    self.models[zone] = Model(**raw)
                except (TypeError, ValueError):
                    _LOGGER.warning('Ignoring invalid stored model for %s', zone)
            self.last_training = saved.get('last_training', 0)
            self.saved_diagnostics = saved.get('diagnostics', {})

    async def _async_update_data(self):
        now_dt = dt.utcnow()
        now = int(now_dt.timestamp())
        local_midnight = dt.as_local(now_dt).replace(hour=0, minute=0, second=0, microsecond=0)
        midnight = int(local_midnight.timestamp())
        # Retrain hourly until *every* configured zone has a model.
        training = now - self.last_training >= (
            86400 if all(zone in self.models for zone in self.config['zones']) else 3600)
        kitchen_entities = [profile[key] for profile in self.config.get('profiles', {}).values()
                            if profile.get('type') == 'kitchen'
                            for key in ('oven_power', 'hob_power', 'hood', 'kitchen_humidity')
                            if profile.get(key)]
        ids = list(dict.fromkeys([*self.config['zones'], *kitchen_entities, *(self.config[key] for key in
              ('outdoor', 'supply', 'return', 'boiler', 'mixed', 'irradiance', 'illuminance', 'pv_power')
              if self.config.get(key)), 'sun.sun']))
        live = {entity: self.hass.states.get(entity) for entity in ids}
        start = min(now_dt - timedelta(days=7 if training else 0, hours=6), local_midnight)
        try:
            history_states = await get_instance(self.hass).async_add_executor_job(partial(
                history.get_significant_states, self.hass, start, now_dt, ids,
                include_start_time_state=True, significant_changes_only=False,
                minimal_response=False, no_attributes=False))
        except Exception:
            _LOGGER.warning('Recorder history query failed', exc_info=True)
            history_states = {}
        data, new_models = await self.hass.async_add_executor_job(
            compute, self.config, history_states, live, now, midnight, dict(self.models),
            training, self.saved_diagnostics)
        if training and history_states:
            self.models = new_models
            self.saved_diagnostics = {zone: {
                'status': values['_training_status'],
                'samples': values['model_samples'],
                **{k: values['model_' + k] for k in (
                    'last_training', 'raw_rows', 'valid_rows', 'missing_room',
                    'missing_outdoor', 'missing_heat', 'heating_samples',
                    'idle_samples', 'temperature_changes', 'candidate_mae',
                    'persistence_mae')},
                'training_heating_pairs': values['model_heating_samples'],
                'training_idle_pairs': values['model_idle_samples'],
                'kitchen_excluded_samples': values['kitchen_excluded_samples'],
                'kitchen_heat_events': values['kitchen_heat_events'],
            } for zone, values in data['zones'].items()}
            self.last_training = now
            await self.store.async_save({'config': self.config, 'last_training': now,
                                         'models': {key: asdict(model) for key, model in self.models.items()},
                                         'diagnostics': self.saved_diagnostics})
        return data
