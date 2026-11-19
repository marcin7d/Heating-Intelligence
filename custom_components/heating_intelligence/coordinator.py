"""Read Recorder and live states, train off the event loop and persist models."""
from dataclasses import asdict
from datetime import timedelta
from functools import partial
import logging
from statistics import median

from homeassistant.components.recorder import get_instance, history
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt

from .model import HORIZONS, STEP, Model, cycles, demand, fit, forecast, heat, temperature

LOGGER = logging.getLogger(__name__)


def boiler_state(state):
    if state is None:
        return None
    value = state.state.lower()
    if value in {"on", "1", "1.0", "heating", "running", "true"}:
        return True
    if value in {"off", "0", "0.0", "idle", "false"}:
        return False
    return None


def temp(state, default_unit, attribute=None):
    if state is None or state.state in {"unknown", "unavailable"}:
        return None
    value = state.attributes.get(attribute) if attribute else state.state
    return temperature(value, state.attributes.get("unit_of_measurement", default_unit))


def request_state(state, room, target):
    if state is None or state.state in {"unknown", "unavailable"}:
        return None
    if state.state == "off":
        return False
    action = state.attributes.get("hvac_action")
    if action is not None:
        return action == "heating" if action in {"heating", "idle", "off", "cooling", "drying", "fan", "preheating", "defrosting"} else None
    if state.state in {"heat", "auto", "heat_cool"} and None not in (room, target):
        return target - room >= 0.3
    return None


def calculate(config, histories, live, unit, now, midnight, models, training, history_ok):
    end = now // STEP * STEP
    sources = {key: config.get(key) for key in ("outdoor", "supply", "return", "mixed", "boiler")}
    kinds = {zone: "floor" if zone in config["floor"] else "radiator" for zone in config["zones"]}
    series = {key: [(int(state.last_updated.timestamp()), state) for state in values] for key, values in histories.items()}
    indices = dict.fromkeys(live, 0)
    current = {}

    def sample(states, key, attr=None):
        fallback = unit if attr else "°C"
        return temp(states.get(key), fallback, attr)

    zone_rows = {zone: [] for zone in kinds}
    start = end - (7 * 86400 if training else 6 * 3600)
    history_stamps = range(start, end, STEP) if history_ok else ()
    for stamp in (*history_stamps, end):
        if stamp == end:
            states = live
        else:
            for key in indices:
                events = series.get(key, [])
                while indices[key] < len(events) and events[indices[key]][0] <= stamp:
                    current[key] = events[indices[key]][1]
                    indices[key] += 1
            states = current
        outdoor = sample(states, sources["outdoor"])
        supply = sample(states, sources["supply"])
        mixed = sample(states, sources["mixed"])
        boiler = boiler_state(states.get(sources["boiler"]))
        for zone, kind in kinds.items():
            room = sample(states, zone, "current_temperature")
            target = sample(states, zone, "temperature")
            request = request_state(states.get(zone), room, target)
            # With a configured mixed sensor, skip gaps instead of changing feature scale.
            fallback_boiler = None if kind == "floor" and sources["mixed"] else boiler
            power = heat(kind, request, fallback_boiler, room, supply, mixed)
            zone_rows[zone].append((stamp, room, outdoor, power))

    if training and history_ok:
        for zone, kind in kinds.items():
            candidate = fit(zone_rows[zone][:-1], kind)
            if candidate:
                models[zone] = candidate

    return_temp = sample(live, sources["return"])
    events = [(stamp, boiler_state(state)) for stamp, state in series.get(sources["boiler"], ())]
    events.append((now, boiler))
    stats = cycles(events, midnight, now) if history_ok else {}
    last_start = next((right[0] for left, right in reversed(list(zip(events, events[1:]))) if left[1] is False and right[1] is True), None)
    result = {
        **stats,
        "delta_t": round(supply - return_temp, 2) if None not in (supply, return_temp) else None,
        "history": "available" if history_ok and any(histories.values()) else "missing",
        "zones": {},
    }
    demands = []
    for zone, kind in kinds.items():
        rows = zone_rows[zone]
        _, room, _, power = rows[-1]
        target = sample(live, zone, "temperature")
        request = request_state(live.get(zone), room, target)
        demands.append((request, target - room if None not in (target, room) else None))
        model = models.get(zone)
        active_power = heat(kind, True, None, room, supply, mixed)
        if kind == "floor" and not sources["mixed"]:
            active_power = 1.0
        else:
            recent_heating = [row[3] for row in rows[:-1] if row[3] is not None and row[3] > 0.25]
            if recent_heating:
                active_power = median(recent_heating)
        estimates, lead = forecast(model, rows, outdoor, power, target, active_power)
        result["zones"][zone] = {
            **{f"t_{minute}": estimates.get(minute) for minute in HORIZONS},
            "lead": lead, "error": round(model.error, 4) if model else None,
            "memory": round(model.memory, 3) if model else None,
        }
    result["demand"], result["advice"] = demand(demands, boiler, last_start, now)
    return result, models


class HeatingCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, LOGGER, config_entry=entry, name="heating_intelligence",
                         update_interval=timedelta(minutes=5))
        self.config = dict(entry.data)
        self.store = Store(hass, 1, f"heating_intelligence.{entry.entry_id}")
        self.models = {}
        self.trained = 0

    async def _async_setup(self):
        saved = await self.store.async_load() or {}
        if saved.get("config") == self.config:
            self.models = {zone: Model(**model) for zone, model in saved.get("models", {}).items()}
            self.trained = saved.get("trained", 0)

    async def _async_update_data(self):
        now = dt.utcnow()
        stamp = int(now.timestamp())
        midnight = dt.as_local(now).replace(hour=0, minute=0, second=0, microsecond=0)
        ids = list(dict.fromkeys([*self.config["zones"], *(self.config[key] for key in
            ("outdoor", "supply", "return", "boiler", "mixed") if self.config.get(key))]))
        live = {key: self.hass.states.get(key) for key in ids}
        training = stamp - self.trained >= (86400 if self.models else 3600)
        start = min(now - timedelta(days=7 if training else 0, hours=6), midnight)
        try:
            histories = await get_instance(self.hass).async_add_executor_job(partial(
                history.get_significant_states, self.hass, start, now, ids,
                include_start_time_state=True, significant_changes_only=False,
                minimal_response=False, no_attributes=False,
            ))
            history_ok = True
        except Exception:
            LOGGER.warning("Recorder history unavailable", exc_info=True)
            histories, history_ok = {}, False
        data, models = await self.hass.async_add_executor_job(
            calculate, self.config, histories, live, self.hass.config.units.temperature_unit,
            stamp, int(midnight.timestamp()), dict(self.models), training, history_ok,
        )
        if training and history_ok:
            self.models, self.trained = models, stamp
            await self.store.async_save({"config": self.config, "trained": stamp,
                                         "models": {zone: asdict(model) for zone, model in models.items()}})
        return data
