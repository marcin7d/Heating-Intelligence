"""Check Kitchen wiring through the full compute path without HA installation.

Only HA service imports are stubbed: real coordinator/model/kitchen logic runs.
"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/heating_intelligence'


def fake_module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    module.__path__ = []
    sys.modules[name] = module
    return module


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fake_module('homeassistant')
fake_module('homeassistant.components')
fake_module('homeassistant.components.recorder', get_instance=lambda _: None,
            history=types.SimpleNamespace())
fake_module('homeassistant.helpers')
fake_module('homeassistant.helpers.storage', Store=object)
fake_module('homeassistant.helpers.update_coordinator', DataUpdateCoordinator=object)
fake_module('homeassistant.util', dt=types.SimpleNamespace())
package = fake_module('hi_kitchen_testing')
package.__path__ = [str(ROOT)]
m = load('hi_kitchen_testing.model', 'model.py')
load('hi_kitchen_testing.kitchen', 'kitchen.py')
c = load('hi_kitchen_testing.coordinator', 'coordinator.py')


class State:
    def __init__(self, state, attributes=None, timestamp=0):
        self.state = str(state)
        self.attributes = attributes or {}
        self.last_updated = datetime.fromtimestamp(timestamp, timezone.utc)


def live_states(oven=700):
    return {
        'climate.kitchen': State('heat', {'current_temperature': 20, 'temperature': 21,
                                          'hvac_action': 'heating'}),
        'climate.bedroom': State('heat', {'current_temperature': 20, 'temperature': 21,
                                          'hvac_action': 'heating'}),
        'sensor.outdoor': State(5),
        'sensor.supply': State(45),
        'sensor.return': State(37),
        'binary_sensor.boiler': State('on'),
        'sensor.oven': State(oven, {'unit_of_measurement': 'W'}),
        'sun.sun': State('above_horizon', {'elevation': 30, 'azimuth': 180}),
        'sensor.irradiance': State(50),
    }


CONFIG = {
    'zones': ['climate.kitchen', 'climate.bedroom'],
    'floor': ['climate.kitchen'],
    'outdoor': 'sensor.outdoor', 'supply': 'sensor.supply',
    'return': 'sensor.return', 'boiler': 'binary_sensor.boiler',
    'irradiance': 'sensor.irradiance',
    'profiles': {
        'climate.kitchen': {'type': 'kitchen', 'oven_power': 'sensor.oven'},
        'climate.bedroom': {'type': 'standard'},
    },
}


class CoordinatorKitchenTests(unittest.TestCase):
    def test_kitchen_event_withholds_only_kitchen_forecast(self):
        models = {
            zone: m.Model(memory=0, loss=.01, gain=.2, solar_gain=0, bias=0,
                          error=.01, baseline=.03, samples=250)
            for zone in CONFIG['zones']
        }
        output, unchanged = c.compute(CONFIG, {}, live_states(), 9_000_000, 8_900_000, models,
                                      training=False)
        kitchen = output['zones']['climate.kitchen']
        bedroom = output['zones']['climate.bedroom']
        self.assertEqual(output['delta_t'], 8)
        self.assertEqual(kitchen['room_profile'], 'kitchen')
        self.assertEqual(kitchen['kitchen_internal_heat'], 'active')
        self.assertEqual(kitchen['kitchen_heat_source'], 'oven')
        self.assertEqual(kitchen['model_status'], 'kitchen_heat_event')
        self.assertIsNone(kitchen['t_60'])
        self.assertEqual(bedroom['room_profile'], 'standard')
        self.assertEqual(bedroom['kitchen_internal_heat'], 'not_applicable')
        self.assertIsNotNone(bedroom['t_60'])
        self.assertEqual(unchanged, models)

    def test_training_diagnostics_explain_empty_history(self):
        output, models = c.compute(CONFIG, {}, live_states(oven=0), 9_000_000,
                                   8_900_000, {}, training=True)
        room = output['zones']['climate.bedroom']
        self.assertEqual(room['model_status'], 'insufficient_valid_samples')
        self.assertEqual(room['model_valid_rows'], 0)
        self.assertEqual(room['model_heating_samples'], 0)
        self.assertEqual(room['model_idle_samples'], 0)
        self.assertIsNotNone(room['model_last_training'])
        self.assertEqual(models, {})

    def test_kitchen_idle_does_not_block_regular_prediction(self):
        model = m.Model(memory=0, loss=.01, gain=.2, solar_gain=0, bias=0,
                        error=.01, baseline=.03, samples=250)
        out, _ = c.compute(CONFIG, {}, live_states(oven=0), 9_000_000, 8_900_000,
                           {'climate.kitchen': model}, training=False)
        kitchen = out['zones']['climate.kitchen']
        self.assertEqual(kitchen['kitchen_internal_heat'], 'none')
        self.assertIsNotNone(kitchen['t_60'])


if __name__ == '__main__':
    unittest.main()
