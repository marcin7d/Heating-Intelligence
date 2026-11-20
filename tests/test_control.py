"""Coupled 3-zone boiler prediction tests without Home Assistant."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/heating_intelligence'
package = types.ModuleType('hi_control_tests')
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package


def load(name):
    spec = importlib.util.spec_from_file_location(
        'hi_control_tests.' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


m = load('model')
ctrl = load('control')


def zone(requested=True, target=25., memory=0., gain=.2, historical_heat=0.):
    model = m.Model(memory=memory, loss=0, gain=gain, solar_gain=0,
                    bias=0, error=0.01, baseline=0.1, samples=300,
                    qualified_horizons=(30, 60, 120, 360))
    rows = [(i * m.STEP, 20., 5., historical_heat, None) for i in range(60)]
    return {'model': model, 'rows': rows, 'room': 20., 'outside': 5.,
            'solar': None, 'requested': requested, 'target': target,
            'active_power': 1.0}


class BoilerRuleTests(unittest.TestCase):
    def test_three_calls_start_after_one_five_minute_period(self):
        self.assertEqual(ctrl.next_boiler_state(False, 3, 0), (True, 0))
        self.assertEqual(ctrl.next_boiler_state(False, 4, 0), (True, 0))

    def test_below_three_turns_off_immediately(self):
        self.assertEqual(ctrl.next_boiler_state(True, 2, 0), (False, 0))
        self.assertEqual(ctrl.next_boiler_state(True, 0, 0), (False, 0))
        self.assertEqual(ctrl.next_boiler_state(True, 3, 0), (True, 0))

    def test_consecutive_demand_duration_and_gaps(self):
        stamps = [(0, 2), (300, 3), (600, 3), (900, 3)]
        self.assertEqual(ctrl.demand_pending_minutes(stamps, False), 5)
        self.assertEqual(ctrl.demand_pending_minutes([(0, 3), (600, 3)], False), 0)
        self.assertEqual(ctrl.demand_pending_minutes([(0, None), (300, 3)], False), 0)

    def test_model_thermostat_hysteresis(self):
        self.assertTrue(ctrl.next_zone_request(True, 20.99, 21))
        self.assertFalse(ctrl.next_zone_request(True, 21, 21))
        self.assertFalse(ctrl.next_zone_request(False, 20.9, 21))
        self.assertTrue(ctrl.next_zone_request(False, 20.6, 21))


class CoupledSimulationTests(unittest.TestCase):
    def test_only_two_zones_cannot_run_boiler(self):
        data = {str(i): zone() for i in range(2)}
        result = ctrl.simulate_system(data, False)
        self.assertEqual(result['boiler'][30], 'off')
        self.assertEqual(result['current_demand'], 2)
        self.assertAlmostEqual(result['temperatures']['0'][30], 20.)

    def test_three_zones_start_and_heat(self):
        data = {str(i): zone(target=40) for i in range(3)}
        result = ctrl.simulate_system(data, False)
        self.assertEqual(result['boiler'][30], 'on')
        self.assertEqual(result['status'], 'conditional')
        self.assertGreater(result['temperatures']['0'][30], 20.)

    def test_zone_satisfied_stops_boiler(self):
        data = {str(i): zone(target=20.1, gain=.3) for i in range(3)}
        result = ctrl.simulate_system(data, False)
        self.assertEqual(result['boiler'][30], 'off')
        self.assertEqual(result['demand'][30], 0)

    def test_stored_radiator_heat_after_boiler_off(self):
        data = {'bedroom': zone(target=40, memory=.9, gain=.15, historical_heat=1)}
        result = ctrl.simulate_system(data, False)
        self.assertEqual(result['boiler'][30], 'off')
        self.assertGreater(result['temperatures']['bedroom'][30], 20.)

    def test_untrained_zone_keeps_count_but_marks_partial(self):
        data = {str(i): zone(target=40) for i in range(3)}
        data['2']['model'] = None
        result = ctrl.simulate_system(data, False)
        self.assertEqual(result['status'], 'partial_untrained_zones')
        self.assertEqual(result['boiler'][30], 'on')
        self.assertEqual(result['temperatures']['2'], {})

    def test_missing_boiler_state_withholds_forecast(self):
        data = {str(i): zone() for i in range(3)}
        result = ctrl.simulate_system(data, None)
        self.assertEqual(result['status'], 'missing_boiler_state')
        self.assertEqual(result['temperatures'], {})


if __name__ == '__main__':
    unittest.main()
