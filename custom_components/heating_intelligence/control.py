"""Read-only coupled boiler/zone forecasting for a threshold-controlled heating system.

A prediction is conditional on constant room targets, external temperature and
nominal heat delivery. It never sends commands to the actual boiler.
"""
from .model import STEP, HORIZONS

MIN_REQUESTING_ZONES = 3
START_DELAY_MIN = 5
THERMOSTAT_DEADBAND_C = 0.3


def next_boiler_state(running, requesting, pending_minutes=0, step_minutes=5):
    """Apply >=3 for five minutes to start; <3 stops without delay."""
    if running is None or requesting is None:
        return None, 0
    if requesting < MIN_REQUESTING_ZONES:
        return False, 0
    if running:
        return True, 0
    pending = max(0, pending_minutes) + step_minutes
    if pending >= START_DELAY_MIN:
        return True, 0
    return False, pending


def demand_pending_minutes(history, boiler_on):
    """Estimate pending start timer conservatively from 5-minute snapshots.

    Counts are (timestamp, number_of_requests_or_None). Do not treat an
    unknown historical request as evidence of five uninterrupted minutes.
    """
    if boiler_on is not False or not history:
        return 0
    current_stamp, current_count = history[-1]
    if current_count is None or current_count < MIN_REQUESTING_ZONES:
        return 0
    pending = 0
    next_stamp = current_stamp
    for stamp, count in reversed(history[:-1]):
        if stamp != next_stamp - STEP or count is None or count < MIN_REQUESTING_ZONES:
            break
        pending += STEP // 60
        next_stamp = stamp
    return min(pending, START_DELAY_MIN)


def next_zone_request(previous, temperature, target):
    """Approximate thermostat hysteresis; never alter the actual thermostat."""
    if previous is None or temperature is None or target is None:
        return previous
    if previous:
        return temperature < target
    return temperature <= target - THERMOSTAT_DEADBAND_C


def _stored_heat(model, rows):
    """Estimate the emitter's thermal memory using known prior delivery."""
    if not rows:
        return None
    recent = rows[-49:-1]
    if model.memory and (len(recent) < 12 or
                         any(row[3] is None for row in recent) or
                         any(b[0] - a[0] != STEP for a, b in zip(recent, recent[1:]))):
        return None
    mass = 0.0
    for row in recent:
        if row[3] is not None:
            mass = model.memory * mass + (1 - model.memory) * row[3]
    return mass


def simulate_system(zones, boiler_on, pending_minutes=0):
    """Run all zones together, updating common boiler state each 5-minute step.

    Each input is a dict with model, rows, room, target, requested, outside,
    solar and active_power. An untrained zone is held at its observed room
    temperature, but still counts toward boiler demand. Its future demand is
    consequently uncertain and the simulation status is marked 'partial'.
    """
    empty = {'temperatures': {}, 'lead': {}, 'boiler': {}, 'demand': {},
             'status': 'missing_data', 'current_demand': None}
    if not zones or boiler_on is None:
        return {**empty, 'status': 'missing_boiler_state' if boiler_on is None else 'missing_zones'}
    if any(zone.get('room') is None or zone.get('requested') is None for zone in zones.values()):
        return {**empty, 'status': 'missing_zone_state'}

    current_demand = sum(zone['requested'] for zone in zones.values())
    states = {}
    partial = False
    for name, zone in zones.items():
        model = zone.get('model')
        if (model is not None and (zone.get('outside') is None or
                (model.uses_solar and zone.get('solar') is None) or
                zone.get('active_power') is None)):
            model = None
        mass = _stored_heat(model, zone.get('rows')) if model is not None else None
        if model is not None and mass is None:
            model = None
        if model is None or not model.qualified_horizons:
            partial = True
            model = None
        states[name] = {'room': zone['room'], 'target': zone.get('target'),
                        'requested': bool(zone['requested']), 'model': model,
                        'mass': mass, 'outside': zone.get('outside'),
                        'solar': zone.get('solar') or 0.0,
                        'active_power': zone.get('active_power'),
                        'lead': 0 if zone.get('target') is not None
                        and zone['room'] >= zone['target'] - 0.1 else None}

    boiler = bool(boiler_on)
    pending = max(0, pending_minutes) if not boiler else 0
    temperature_forecasts = {name: {} for name in zones}
    lead = {}
    future_boiler = {}
    future_demand = {}
    for minutes in range(5, max(HORIZONS) + 1, STEP // 60):
        count = sum(state['requested'] for state in states.values())
        boiler, pending = next_boiler_state(boiler, count, pending)
        for name, state in states.items():
            model = state['model']
            if model is not None:
                heat = state['active_power'] if boiler and state['requested'] else 0.0
                state['mass'] = model.memory * state['mass'] + (1 - model.memory) * heat
                t = state['room']
                state['room'] = (t + model.loss * (state['outside'] - t)
                                 + model.gain * state['mass']
                                 + model.solar_gain * state['solar'] + model.bias)
                if (state['lead'] is None and state['target'] is not None
                        and state['room'] >= state['target'] - .1):
                    state['lead'] = minutes
            state['requested'] = next_zone_request(
                state['requested'], state['room'], state['target'])
        if minutes in HORIZONS:
            future_boiler[minutes] = 'on' if boiler else 'off'
            future_demand[minutes] = sum(state['requested'] for state in states.values())
            for name, state in states.items():
                if state['model'] is not None and minutes in state['model'].qualified_horizons:
                    temperature_forecasts[name][minutes] = round(state['room'], 2)

    for name, state in states.items():
        if state['model'] is not None and 120 in state['model'].qualified_horizons:
            lead[name] = state['lead']
    return {'temperatures': temperature_forecasts, 'lead': lead,
            'boiler': future_boiler, 'demand': future_demand,
            'status': 'partial_untrained_zones' if partial else 'conditional',
            'current_demand': current_demand}
