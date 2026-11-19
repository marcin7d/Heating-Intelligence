"""Pure helpers for detecting non-heating kitchen gains.

Events are treated as a disturbance to room-temperature learning, NOT as a
measured thermal power or a reliable forecast of future cooking.
"""
from dataclasses import dataclass
from math import isfinite


def power_watts(value, unit='W'):
    """Normalize power sensors (not cumulative energy) to watts."""
    if unit not in ('W', 'kW', ''):
        return None
    try:
        power = float(value) * (1000 if unit == 'kW' else 1)
    except (TypeError, ValueError):
        return None
    return power if isfinite(power) and power >= 0 else None


def humidity_percent(value, unit='%'):
    if unit not in ('%', ''):
        return None
    try:
        rh = float(value)
    except (TypeError, ValueError):
        return None
    return rh if isfinite(rh) and 0 <= rh <= 100 else None

STEP = 300
COOLDOWN_STEPS = 6  # 30 minutes after last disturbance
POWER_THRESHOLD_W = 150.0
HUMIDITY_RISE_PCT = 6.0
RAPID_RISE_C = 0.25


@dataclass(frozen=True)
class KitchenObservation:
    timestamp: int
    room: float | None
    heating: float | None
    solar: float | None
    oven_power: float | None = None
    hob_power: float | None = None
    hood_on: bool | None = None
    humidity: float | None = None


def _valid_power(value):
    return value is not None and isfinite(value) and value >= 0


def disturbance_reason(now: KitchenObservation, before: KitchenObservation | None):
    """Return a reason, or None. Appliance evidence takes priority.

    Fast warming alone is considered only when heating and measured sunlight
    are low, to avoid misclassifying normal radiator response and sunshine.
    """
    if _valid_power(now.oven_power) and now.oven_power >= POWER_THRESHOLD_W:
        return 'oven'
    if _valid_power(now.hob_power) and now.hob_power >= POWER_THRESHOLD_W:
        return 'hob'
    if now.hood_on is True:
        return 'hood'
    if before is None or now.timestamp - before.timestamp != STEP:
        return None
    if (now.humidity is not None and before.humidity is not None
            and 0 <= now.humidity <= 100 and 0 <= before.humidity <= 100
            and now.humidity - before.humidity >= HUMIDITY_RISE_PCT):
        return 'humidity_rise'
    if (now.room is not None and before.room is not None
            and now.heating is not None and now.heating <= 0.1
            and now.solar is not None and now.solar <= 0.12
            and now.room - before.room >= RAPID_RISE_C):
        return 'unexpected_warming'
    return None


def mark_disturbances(rows, observations, cooldown_steps=COOLDOWN_STEPS):
    """Mask disturbed training samples, and describe the latest event state.

    Does not remove times or join segments: setting the heat input to None
    makes model._samples reset its thermal-memory history across the event.
    The input rows remain unmodified for live prediction and diagnostics.

    Returns (filtered_rows, current_state, last_reason, excluded_count, event_count).
    """
    if len(rows) != len(observations):
        raise ValueError('Observation and training lengths must match')
    masked = []
    previous = None
    last_reason = 'none'
    hold_until = None
    current_state = 'none'
    excluded = 0
    events = 0
    previous_event = False
    for row, observation in zip(rows, observations):
        reason = disturbance_reason(observation, previous)
        active = reason is not None
        if active:
            if not previous_event:
                events += 1
            hold_until = observation.timestamp + cooldown_steps * STEP
            last_reason = reason
            status = 'active'
        elif hold_until is not None and observation.timestamp <= hold_until:
            status = 'cooldown'
        else:
            status = 'none'
            last_reason = 'none'
        previous_event = active
        current_state = status
        if status != 'none':
            stamp, room, outdoor, _, solar = row
            masked.append((stamp, room, outdoor, None, solar))
            excluded += 1
        else:
            masked.append(row)
        previous = observation
    return masked, current_state, last_reason, excluded, events
