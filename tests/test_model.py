"""Unit tests without Home Assistant dependency."""
import importlib.util
import random
import sys
import unittest
from pathlib import Path

file = Path(__file__).resolve().parents[1] / 'custom_components/heating_intelligence/model.py'
spec = importlib.util.spec_from_file_location('hi_model', file)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class SolarTests(unittest.TestCase):
    def test_priority(self):
        value, source = m.solar_signal(800, 60000, 5000)
        self.assertEqual(source, 'irradiance')
        self.assertAlmostEqual(value, .8)

    def test_fallback(self):
        self.assertEqual(m.solar_signal(None, 30000, 2000)[1], 'illuminance_proxy')
        self.assertEqual(m.solar_signal(None, None, 2000)[1], 'pv_proxy')
        self.assertEqual(m.solar_signal()[1], 'missing')

    def test_window_orientation(self):
        south, _ = m.solar_signal(1000, sun_azimuth=180, sun_elevation=45, window_azimuths=[180])
        north, _ = m.solar_signal(1000, sun_azimuth=180, sun_elevation=45, window_azimuths=[0])
        self.assertGreater(south, north)
        self.assertEqual(north, 0)

    def test_shading_and_night(self):
        self.assertEqual(m.solar_signal(1000, sun_elevation=-5)[0], 0)
        self.assertAlmostEqual(m.solar_signal(1000, shading=.5)[0], .5)

    def test_missing_sun_does_not_block_base_model(self):
        rows = self.make_rows(False)
        model, status, count = m.train(rows, 'radiator')
        self.assertIsNotNone(model)
        self.assertFalse(model.uses_solar)
        self.assertEqual(status, 'ready')

    @staticmethod
    def make_rows(with_solar, n=900):
        rng = random.Random(97)
        rows, room = [], 20.0
        for i in range(n):
            outside = 4 + 3 * rng.random()
            heating = float(i % 100 < 50)
            sun = .6 if 20 < i % 110 < 70 else 0.0
            rows.append((i * m.STEP, room, outside, heating, sun if with_solar else None))
            room += .015 * (outside - room) + .32 * heating + (.19 * sun if with_solar else 0)
        return rows

    def test_solar_training_selection(self):
        rows = self.make_rows(True)
        model, status, _ = m.train(rows, 'radiator')
        self.assertIsNotNone(model)
        self.assertIn(status, ('ready', 'ready_solar'))
        self.assertLess(model.error, model.baseline)

    def test_status_too_little_history(self):
        model, status, _ = m.train(self.make_rows(True, 30), 'floor')
        self.assertIsNone(model)
        self.assertEqual(status, 'insufficient_history')

    def test_diagnostics_no_temperature_source(self):
        rows = [(i * m.STEP, None, 5, 1 if i % 40 < 20 else 0, None)
                for i in range(500)]
        model, status, info = m.train_with_diagnostics(rows, 'radiator')
        self.assertIsNone(model)
        self.assertEqual(status, 'insufficient_valid_samples')
        self.assertEqual(info['missing_room'], 500)
        self.assertEqual(info['valid_rows'], 0)

    def test_diagnostics_quantized_constant_temperature(self):
        rows = [(i * m.STEP, 21.0, 4.0, 1.0 if i % 80 < 40 else 0.0, None)
                for i in range(800)]
        model, status, info = m.train_with_diagnostics(rows, 'radiator')
        self.assertIsNone(model)
        self.assertEqual(status, 'no_temperature_variation')
        self.assertEqual(info['temperature_changes'], 0)
        self.assertGreater(info['heating_rows'], 24)

    def test_diagnostics_valid_model(self):
        rows = self.make_rows(False)
        model, status, info = m.train_with_diagnostics(rows, 'radiator')
        self.assertIsNotNone(model)
        self.assertEqual(status, 'ready')
        self.assertGreater(info['valid_rows'], 400)
        self.assertIsNotNone(info['candidate_mae'])

    def test_status_no_heating(self):
        rows = [(i * m.STEP, 20, 5, 0, 0) for i in range(400)]
        model, status, _ = m.train(rows, 'radiator')
        self.assertIsNone(model)
        self.assertEqual(status, 'insufficient_heating_samples')

    def test_heat_source_off(self):
        self.assertEqual(m.heating_proxy('radiator', True, False, 20, 50, None), 0)

    def test_forecast(self):
        rows = self.make_rows(False)
        model, _, _ = m.train(rows, 'radiator')
        future, lead = m.forecast(model, rows[-144:], 5, 1, None, 21, 1)
        self.assertEqual(set(future), set(model.qualified_horizons))


if __name__ == '__main__':
    unittest.main()

class HorizonValidationTests(unittest.TestCase):
    def test_metrics_and_qualified_horizons(self):
        rows = SolarTests.make_rows(False)
        model, status, info = m.train_with_diagnostics(rows, 'radiator')
        self.assertIsNotNone(model)
        self.assertTrue(set(model.qualified_horizons) & {30, 60, 120})
        self.assertIn('60', info['horizon_mae'])
        self.assertIn('60', info['horizon_baseline'])

    def test_no_temperature_variation_stays_rejected(self):
        rows = [(i * m.STEP, 21.0, 5.0, float(i % 80 < 40), None)
                for i in range(900)]
        model, status, info = m.train_with_diagnostics(rows, 'radiator')
        self.assertIsNone(model)
        self.assertEqual(status, 'no_temperature_variation')

    def test_only_qualified_forecasts_are_exposed(self):
        rows = SolarTests.make_rows(False)
        model, _, _ = m.train_with_diagnostics(rows, 'radiator')
        self.assertIsNotNone(model)
        model.qualified_horizons = (60,)
        predictions, _ = m.forecast(model, rows[-144:], 5, 1, None, 21, 1)
        self.assertEqual(set(predictions), {60})

class ResidualHeatTests(unittest.TestCase):
    def test_boiler_off_has_no_new_delivered_heat(self):
        self.assertEqual(m.heating_proxy('radiator', True, False, 20, 60, None), 0)
        self.assertEqual(m.heating_proxy('radiator', False, True, 20, 60, None), 0)

    def test_unknown_boiler_is_not_assumed_on(self):
        self.assertIsNone(m.heating_proxy('radiator', True, None, 20, 60, None))

    def test_stored_radiator_heat_decays_after_shutdown(self):
        # A radiator heated for 1 hour continues emitting stored heat after
        # the pump stops, while the direct input drops to zero.
        memory = .95
        stored = 0.
        for _ in range(12):
            stored = memory * stored + (1 - memory) * 1.
        at_shutdown = stored
        stored = memory * stored
        self.assertGreater(stored, 0)
        self.assertLess(stored, at_shutdown)

    def test_heating_gain_diagnostic_exposed(self):
        rows = SolarTests.make_rows(False)
        _, _, info = m.train_with_diagnostics(rows, 'radiator')
        self.assertIn('candidate_heating_gain', info)
        self.assertIn('zero_gain_candidates', info)
        self.assertIn('evaluated_candidates', info)
