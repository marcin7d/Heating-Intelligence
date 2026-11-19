"""Five-minute thermal model and boiler diagnostics."""
from dataclasses import dataclass
from math import isfinite

STEP = 300
HORIZONS = (30, 60, 120, 360)


def temperature(value, unit="°C"):
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    if unit == "°F":
        value = (value - 32) * 5 / 9
    elif unit != "°C":
        return None
    return value if isfinite(value) and -80 <= value <= 130 else None


def heat(kind, request, boiler, room, supply, mixed):
    """Normalized heat proxy. A floor loop never uses boiler supply."""
    if request is False:
        return 0.0
    water = mixed if kind == "floor" else supply
    if request is None or room is None:
        return None
    if water is None:
        return float(boiler) if kind == "floor" and boiler is not None else None
    return max(0.0, water - room) / (15 if kind == "floor" else 30)


@dataclass
class Model:
    memory: float
    loss: float
    gain: float
    bias: float
    error: float
    baseline: float
    samples: int


def features(rows, memory):
    """Rows are (timestamp, room, outdoor, heat proxy). Reset across gaps."""
    thermal, previous, warm = 0.0, None, 0
    for stamp, room, outdoor, power in rows:
        if previous is None or stamp - previous[0] != STEP:
            thermal, previous, warm = 0.0, None, 0
        if None in (room, outdoor, power):
            previous = None
            continue
        if previous is not None:
            _, old_room, old_outdoor, old_power = previous
            thermal = memory * thermal + (1 - memory) * old_power
            warm += 1
            if warm >= (12 if memory else 1):
                yield ((old_outdoor - old_room, thermal, 1.0), room - old_room, old_power)
        previous = stamp, room, outdoor, power


def fit(rows, kind):
    """Fit on an earlier interval and score sequential one-step holdout."""
    candidates = []
    for memory in ((0.8, 0.9, 0.95, 0.975) if kind == "floor" else (0.0, 0.5, 0.75)):
        pairs = list(features(rows, memory))
        split = int(len(pairs) * 0.8)
        if split < 144 or sum(power > 0.25 for _, _, power in pairs[:split]) < 24 or sum(power < 0.1 for _, _, power in pairs[:split]) < 24:
            continue
        train = [(x, y) for x, y, _ in pairs[:split]]
        holdout = [(x, y) for x, y, _ in pairs[split:]]
        coefficients = [0.0, 0.0, 0.0]
        # Center the regressors to decouple the offset from the outdoor gradient.
        means = [sum(x[j] for x, _ in train) / len(train) for j in range(2)]
        target_mean = sum(y for _, y in train) / len(train)
        centered = [((x[0] - means[0], x[1] - means[1]), y - target_mean) for x, y in train]
        for _ in range(40):
            for j, (lo, hi) in enumerate(((0, 0.1), (0, 1))):
                other = 1 - j
                numerator = sum(x[j] * (y - x[other] * coefficients[other]) for x, y in centered)
                denominator = sum(x[j] ** 2 for x, _ in centered) + 0.01
                coefficients[j] = min(hi, max(lo, numerator / denominator))
        coefficients[2] = min(0.1, max(-0.1, target_mean - sum(a * b for a, b in zip(means, coefficients))))
        error = sum(abs(y - sum(a * b for a, b in zip(x, coefficients))) for x, y in holdout) / len(holdout)
        baseline = sum(abs(y) for _, y in holdout) / len(holdout)
        if coefficients[1] > 0 and error < baseline:
            candidates.append(Model(memory, *coefficients, error, baseline, len(pairs)))
    return min(candidates, key=lambda model: model.error, default=None)


def forecast(model, rows, outdoor, power, target, active_power):
    """Constant outdoor and heat scenarios. Initial memory comes from real history."""
    if not model or not rows or None in (outdoor, power, rows[-1][1]):
        return {}, None
    energy, next_stamp = 0.0, rows[-1][0]
    for stamp, _, _, past_power in reversed(rows[:-1]):
        if stamp != next_stamp - STEP or past_power is None:
            break
        energy += (1 - model.memory) * model.memory ** ((rows[-1][0] - stamp) // STEP - 1) * past_power
        next_stamp = stamp
    if model.memory and rows[-1][0] - next_stamp < 12 * STEP:
        return {}, None

    def simulate(heat_input):
        room, mass = rows[-1][1], energy
        for minute in range(5, 361, 5):
            mass = model.memory * mass + (1 - model.memory) * heat_input
            room += model.loss * (outdoor - room) + model.gain * mass + model.bias
            yield minute, room

    predictions = {minute: round(room, 2) for minute, room in simulate(power) if minute in HORIZONS}
    lead = None
    if target is not None:
        if rows[-1][1] >= target - 0.1:
            lead = 0
        elif active_power is not None and active_power > 0:
            lead = next((minute for minute, room in simulate(active_power) if room >= target - 0.1), None)
    return predictions, lead


def cycles(events, start, end):
    """Transitions with known predecessors, clipped runtime, complete cycles."""
    previous, cursor, opened = None, start, None
    starts, runtime, covered, lengths = 0, 0, 0, []
    for stamp, state in [*events, (end, None)]:
        if stamp > end:
            break
        elapsed = max(0, stamp - cursor)
        covered += elapsed if previous is not None else 0
        runtime += elapsed if previous is True else 0
        if stamp >= start and state is True and previous is False:
            starts += 1
            opened = stamp
        if state is not True:
            if state is False and opened is not None:
                lengths.append(stamp - opened)
            opened = None
        previous, cursor = state, max(start, stamp)
    return {
        "starts": starts if covered else None,
        "runtime": round(runtime / 60, 1) if covered else None,
        "cycle": round(sum(lengths) / len(lengths) / 60, 1) if lengths else None,
        "coverage": round(100 * covered / (end - start), 1) if end > start else None,
    }


def demand(zones, boiler, last_start, now):
    """Advisory only. Never infer minimum hydraulic flow from room count."""
    active = [error for request, error in zones if request is True and error is not None]
    if not active and any(request is None or (request and error is None) for request, error in zones):
        return None, "insufficient_data"
    score = round(sum(min(1, max(0, error)) for error in active), 2)
    if not active:
        return score, "no_demand"
    if boiler is None:
        return score, "insufficient_data"
    if boiler:
        return score, "running"
    if score >= 1.5 or max(active) >= 0.8:
        return score, "consider_heat"
    if last_start is not None and now - last_start < 900:
        return score, "recent_start_low_demand"
    return score, "low_demand"
