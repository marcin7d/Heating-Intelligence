"""Small, bounded models for demand and thermal response; no HA dependency."""
from dataclasses import dataclass, asdict, field
from datetime import datetime
from math import cos, radians, isfinite
from statistics import mean

STEP = 300
HORIZONS = (30, 60, 120, 360)


def numeric(x):
    try:
        a = float(x)
        return a if isfinite(a) else None
    except (TypeError, ValueError):
        return None


def temp(x, unit='°C'):
    x = numeric(x)
    if x is None:
        return None
    if unit in ('°F', 'F'):
        x = (x - 32) * 5 / 9
    elif unit not in ('°C', 'C', ''):
        return None
    return x if -80 <= x <= 130 else None


def solar_signal(irradiance=None, illuminance=None, pv_power=None, sun_azimuth=None,
                 sun_elevation=None, window_azimuths=None, shading=0.0):
    """Dimensionless solar proxy; uses W/m² first, lux/PV only as fallback.

    No fixed lux->W/m² conversion is claimed. Angular exposure is deliberately
    approximate; blind/trees/roof losses are learned into the zone coefficient.
    """
    rad, lux, pv = (numeric(v) for v in (irradiance, illuminance, pv_power))
    if rad is not None and rad >= 0:
        base = min(rad / 1000, 1.5)
        source = 'irradiance'
    elif lux is not None and lux >= 0:
        base = min(lux / 100000, 1.5)
        source = 'illuminance_proxy'
    elif pv is not None and pv >= 0:
        # Not a physical irradiance conversion; user-provided rated PV power is unknown.
        base = min(pv / 5000, 1.5)
        source = 'pv_proxy'
    else:
        return None, 'missing'
    elevation = numeric(sun_elevation)
    azimuth = numeric(sun_azimuth)
    if elevation is not None and elevation <= 0:
        return 0.0, source
    if window_azimuths and azimuth is not None:
        directions = [numeric(x) for x in window_azimuths]
        directions = [x for x in directions if x is not None]
        exposure = max((max(0.0, cos(radians(azimuth - direction))) for direction in directions), default=0.0)
    else:
        exposure = 1.0
    return round(base * exposure * (1 - min(1, max(0, shading))), 6), source


@dataclass
class Model:
    memory: float
    loss: float
    gain: float
    solar_gain: float
    bias: float
    error: float
    baseline: float
    samples: int
    uses_solar: bool = False
    qualified_horizons: tuple = ()
    horizon_mae: dict = field(default_factory=dict)
    horizon_baseline: dict = field(default_factory=dict)


def _samples(rows, memory, with_solar):
    """Rows: timestamp, room, outdoor, heating proxy, sunlight proxy."""
    mass = 0.0
    previous = None
    warmup = 0
    for stamp, t, outdoors, heating, solar in rows:
        if previous is None or stamp - previous[0] != STEP:
            mass = 0.0
            previous = None
            warmup = 0
        if any(x is None for x in (t, outdoors, heating)) or (with_solar and solar is None):
            previous = None
            continue
        if previous is not None:
            _, old_t, old_outdoors, old_heating, old_solar = previous
            mass = memory * mass + (1 - memory) * old_heating
            warmup += 1
            if warmup >= (12 if memory > 0 else 1):
                x = (old_outdoors - old_t, mass, old_solar if with_solar else 0.0, 1.0)
                yield x, t - old_t, old_heating
        previous = (stamp, t, outdoors, heating, solar)


def _fit_linear(pairs, with_solar):
    # Bounded coordinate descent on real samples, trained chronologically.
    training_size = int(len(pairs) * .8)
    train, validation = pairs[:training_size], pairs[training_size:]
    if training_size < 144 or len(validation) < 10:
        return None
    if sum(h > .25 for _, _, h in train) < 24 or sum(h < .1 for _, _, h in train) < 24:
        return None
    xs, ys = [p[0] for p in train], [p[1] for p in train]
    means = [mean(row[j] for row in xs) for j in range(3)]
    mean_y = mean(ys)
    centered = [([x[j] - means[j] for j in range(3)], y - mean_y) for x, y in zip(xs, ys)]
    coef = [0.0, 0.0, 0.0]
    bounds = [(0, .1), (0, 1), (0, .25 if with_solar else 0)]
    for _ in range(60):
        for j in range(3):
            lo, hi = bounds[j]
            num = sum(row[j] * (y - sum(coef[k] * row[k] for k in range(3) if k != j)) for row, y in centered)
            den = sum(row[j] ** 2 for row, _ in centered) + .01
            coef[j] = min(hi, max(lo, num / den))
    bias = min(.1, max(-.1, mean_y - sum(means[j] * coef[j] for j in range(3))))
    error = mean(abs(y - sum(c*x for c, x in zip((*coef, bias), row))) for row, y, _ in validation)
    baseline = mean(abs(y) for _, y, _ in validation)
    return coef, bias, error, baseline



def validate_horizons(rows, model):
    """Evaluate 30/60/120/360-minute rollouts on chronological holdout data.

    Only the inputs at the forecast origin are used in each rollout, matching
    live forecasting. No future weather, heating or room data leaks into it.
    """
    split = int(len(rows) * .8)
    result = {}
    for horizon in HORIZONS:
        steps = horizon // 5
        errors, baselines = [], []
        for i in range(max(split, 48), len(rows) - steps, 6):
            origin, future = rows[i], rows[i + steps]
            recent = rows[i - 48:i + 1]
            if future[0] - origin[0] != steps * STEP:
                continue
            if None in (origin[1], origin[2], origin[3], future[1]):
                continue
            if model.uses_solar and origin[4] is None:
                continue
            if any(r[3] is None for r in recent):
                continue
            if any(b[0] - a[0] != STEP for a, b in zip(recent, recent[1:])):
                continue
            mass = 0.
            for r in recent[:-1]:
                mass = model.memory * mass + (1 - model.memory) * r[3]
            temperature = origin[1]
            for _ in range(steps):
                mass = model.memory * mass + (1 - model.memory) * origin[3]
                temperature += (model.loss * (origin[2] - temperature)
                                + model.gain * mass
                                + model.solar_gain * (origin[4] or 0)
                                + model.bias)
            errors.append(abs(temperature - future[1]))
            baselines.append(abs(origin[1] - future[1]))
        if len(errors) >= 8:
            result[horizon] = (mean(errors), mean(baselines))
    return result


def train_with_diagnostics(rows, kind):
    """Return candidate, explanation and source/sample quality metrics.

    The training decision remains conservative: diagnostics make rejection
    explainable rather than claiming an unvalidated thermal model is usable.
    """
    valid = [(stamp, t, outdoor, power, solar) for stamp, t, outdoor, power, solar in rows
             if None not in (t, outdoor, power)]
    info = {
        'raw_rows': len(rows),
        'valid_rows': len(valid),
        'missing_room': sum(t is None for _, t, _, _, _ in rows),
        'missing_outdoor': sum(outdoor is None for _, _, outdoor, _, _ in rows),
        'missing_heat': sum(power is None for _, _, _, power, _ in rows),
        'heating_rows': sum(power > .25 for _, _, _, power, _ in valid),
        'idle_rows': sum(power < .1 for _, _, _, power, _ in valid),
        'temperature_changes': sum(abs(a[1] - b[1]) >= .049
                                   for a, b in zip(valid, valid[1:])
                                   if b[0] - a[0] == STEP),
        'usable_pairs': 0,
        'training_heating_pairs': 0,
        'training_idle_pairs': 0,
        'candidate_mae': None,
        'persistence_mae': None,
        'horizon_mae': {},
        'horizon_baseline': {},
        'qualified_horizons': [],
    }
    if len(rows) < 220:
        return None, 'insufficient_history', info
    memories = (.8, .9, .95, .975) if kind == 'floor' else (0, .5, .75)
    candidates = []
    best_attempt = None
    had_balanced_pairs = False
    for memory in memories:
        for use_solar in (False, True):
            pairs = list(_samples(rows, memory, use_solar))
            split = int(len(pairs) * .8)
            heating_pairs = sum(heat > .25 for _, _, heat in pairs[:split])
            idle_pairs = sum(heat < .1 for _, _, heat in pairs[:split])
            if not use_solar and len(pairs) > info['usable_pairs']:
                info['usable_pairs'] = len(pairs)
                info['training_heating_pairs'] = heating_pairs
                info['training_idle_pairs'] = idle_pairs
            if len(pairs) < 190 or split < 144 or len(pairs) - split < 10:
                continue
            if heating_pairs < 24 or idle_pairs < 24:
                continue
            had_balanced_pairs = True
            fitted = _fit_linear(pairs, use_solar)
            if fitted is None:
                continue
            coefficients, bias, error, baseline = fitted
            if info['candidate_mae'] is None or error < info['candidate_mae']:
                info['candidate_mae'] = round(error, 5)
                info['persistence_mae'] = round(baseline, 5)
            if coefficients[1] <= 0:
                continue
            model = Model(memory, coefficients[0], coefficients[1],
                          coefficients[2], bias, error, baseline,
                          len(pairs), use_solar)
            scores = validate_horizons(rows, model)
            model.horizon_mae = {str(h): round(a, 5) for h, (a, b) in scores.items()}
            model.horizon_baseline = {str(h): round(b, 5) for h, (a, b) in scores.items()}
            model.qualified_horizons = tuple(h for h, (a, b) in scores.items()
                                             if b > 0 and a < b)
            important = [h for h in (30, 60, 120) if h in model.qualified_horizons]
            improvement = sum(1 - scores[h][0] / scores[h][1] for h in important)
            score = (len(important), improvement, -error)
            if best_attempt is None or score > best_attempt[0]:
                best_attempt = (score, model)
            if important:
                candidates.append((score, model))
    if best_attempt:
        attempt = best_attempt[1]
        info.update(horizon_mae=attempt.horizon_mae,
                    horizon_baseline=attempt.horizon_baseline,
                    qualified_horizons=list(attempt.qualified_horizons))
    if not candidates:
        if info['usable_pairs'] < 190:
            status = 'insufficient_valid_samples'
        elif info['training_heating_pairs'] < 24:
            status = 'insufficient_heating_samples'
        elif info['training_idle_pairs'] < 24:
            status = 'insufficient_idle_samples'
        elif info['temperature_changes'] == 0:
            status = 'no_temperature_variation'
        elif not had_balanced_pairs:
            status = 'missing_heating_cycles'
        else:
            status = 'validation_failed'
        return None, status, info
    base = max((x for x in candidates if not x[1].uses_solar),
               key=lambda x: x[0], default=None)
    solar = max((x for x in candidates if x[1].uses_solar),
                key=lambda x: x[0], default=None)
    chosen = base
    if solar and (base is None or solar[0][0] > base[0][0] or
                  (solar[0][0] == base[0][0] and solar[0][1] > base[0][1] * 1.03)):
        chosen = solar
    if chosen:
        model = chosen[1]
        info.update(horizon_mae=model.horizon_mae,
                    horizon_baseline=model.horizon_baseline,
                    qualified_horizons=list(model.qualified_horizons))
        return model, 'ready_solar' if model.uses_solar else 'ready', info
    return None, 'validation_failed', info

def train(rows, kind):
    """Backward-compatible training interface for existing callers/tests."""
    model, reason, info = train_with_diagnostics(rows, kind)
    return model, reason, model.samples if model else info['raw_rows']


def forecast(model, rows, outside, heat_input, solar_now, target, active_heat):
    if model is None or not rows or None in (outside, heat_input, rows[-1][1]):
        return {}, None
    if model.uses_solar and solar_now is None:
        return {}, None
    energy = 0.0
    recent = rows[-49:-1]
    if model.memory and (len(recent) < 12 or
                         any(r[3] is None for r in recent) or
                         any(b[0] - a[0] != STEP for a, b in zip(recent, recent[1:]))):
        return {}, None
    for _, _, _, old_heat, _ in recent:
        if old_heat is not None:
            energy = model.memory * energy + (1 - model.memory) * old_heat

    def simulate(power):
        room, mass = rows[-1][1], energy
        for minutes in range(5, 361, 5):
            mass = model.memory * mass + (1 - model.memory) * power
            room += (model.loss * (outside - room) + model.gain * mass
                     + model.solar_gain * (solar_now or 0) + model.bias)
            yield minutes, room

    qualified = set(model.qualified_horizons)
    predicted = {mins: round(value, 2) for mins, value in simulate(heat_input)
                 if mins in qualified}
    lead = None
    if target is not None and 120 in qualified:
        if rows[-1][1] >= target - .1:
            lead = 0
        elif active_heat is not None and active_heat > 0:
            lead = next((mins for mins, value in simulate(active_heat) if value >= target - .1), None)
    return predicted, lead


def heating_proxy(kind, request, boiler, room, supply, mixed):
    if request is False:
        return 0.0
    if request is None or room is None:
        return None
    if boiler is False:
        return 0.0
    water = mixed if kind == 'floor' else supply
    if water is None:
        return float(boiler) if boiler is not None and kind == 'floor' else None
    return max(0, water - room) / (15 if kind == 'floor' else 30)


def boiler_cycles(events, start, end):
    previous, cursor, opened = None, start, None
    starts, runtime, covered, lengths = 0, 0, 0, []
    for timestamp, value in [*events, (end, None)]:
        if timestamp > end:
            break
        duration = max(0, timestamp - cursor)
        if previous is not None:
            covered += duration
            if previous:
                runtime += duration
        if value is True and previous is False:
            starts += 1
            opened = timestamp
        if value is False and opened is not None:
            lengths.append(timestamp - opened)
            opened = None
        if value is None:
            opened = None
        previous, cursor = value, max(start, timestamp)
    return {'starts': starts if covered else None,
            'runtime': round(runtime / 60, 1) if covered else None,
            'cycle': round(mean(lengths) / 60, 1) if lengths else None,
            'coverage': round(100 * covered / max(1, end - start), 1)}


def demand(zones, boiler):
    usable = [(request, gap) for request, gap in zones if request is not None and gap is not None]
    if not usable:
        return None, 'insufficient_data'
    index = round(sum(min(1, max(0, gap)) for request, gap in usable if request), 2)
    if index == 0:
        return index, 'no_demand'
    if boiler is None:
        return index, 'insufficient_data'
    if boiler:
        return index, 'running'
    return index, 'consider_heat' if index >= 1.5 or any(gap >= .8 for request, gap in usable if request) else 'low_demand'
