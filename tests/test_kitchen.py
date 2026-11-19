"""Tests for Kitchen-only disturbance detection and protection of training."""
import importlib.util
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/heating_intelligence'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


k = load('hi_kitchen', 'kitchen.py')
m = load('hi_thermal', 'model.py')


class KitchenTests(unittest.TestCase):
    def obs(self, minute, temp=20, heating=0, solar=0, oven=None, hob=None,
            hood=None, humidity=45):
        return k.KitchenObservation(minute * 60, temp, heating, solar,
                                    oven, hob, hood, humidity)

    def test_power_normalization(self):
        self.assertEqual(k.power_watts('0.8', 'kW'), 800)
        self.assertEqual(k.power_watts('900', 'W'), 900)
        self.assertIsNone(k.power_watts('900', 'kWh'))
        self.assertIsNone(k.power_watts(-20, 'W'))
        self.assertIsNone(k.power_watts('unavailable'))
        self.assertEqual(k.humidity_percent('85', '%'), 85)
        self.assertIsNone(k.humidity_percent('10', 'g/m³'))

    def test_appliance_and_hood_detected(self):
        self.assertEqual(k.disturbance_reason(self.obs(5, oven=800), None), 'oven')
        self.assertEqual(k.disturbance_reason(self.obs(5, hob=1200), None), 'hob')
        self.assertEqual(k.disturbance_reason(self.obs(5, hood=True), None), 'hood')
        self.assertIsNone(k.disturbance_reason(self.obs(5, oven=80, hob=80, hood=False), None))

    def test_humidity_spike(self):
        self.assertEqual(k.disturbance_reason(self.obs(5, humidity=53), self.obs(0, humidity=45)), 'humidity_rise')
        self.assertIsNone(k.disturbance_reason(self.obs(6, humidity=53), self.obs(0, humidity=45)))

    def test_unexpected_warming_only_without_known_heat_or_sun(self):
        prev = self.obs(0, temp=20)
        self.assertEqual(k.disturbance_reason(self.obs(5, temp=20.3), prev), 'unexpected_warming')
        self.assertIsNone(k.disturbance_reason(self.obs(5, temp=20.3, heating=1), prev))
        self.assertIsNone(k.disturbance_reason(self.obs(5, temp=20.3, solar=0.5), prev))
        self.assertIsNone(k.disturbance_reason(self.obs(5, temp=20.3, solar=None), prev))

    def test_mask_event_and_six_following_samples(self):
        rows = [(i * k.STEP, 20 + i * 0.01, 4, 0.5, 0.0) for i in range(12)]
        obs = [self.obs(i * 5, temp=20 + i * 0.01, heating=0.5, oven=900 if i == 2 else 0)
               for i in range(12)]
        filtered, status, source, excluded, events = k.mark_disturbances(rows, obs)
        self.assertEqual((status, source, excluded, events), ('none', 'none', 7, 1))
        self.assertEqual(filtered[2][3], None)
        self.assertEqual(filtered[8][3], None)
        self.assertEqual(filtered[9][3], 0.5)
        self.assertEqual(rows[2][3], 0.5)  # source data never modified

    def test_current_event_suppresses_persistent_model_predictions_at_call_site(self):
        rows = [(i * k.STEP, 20, 4, 0, 0.0) for i in range(14)]
        obs = [self.obs(i * 5, heating=0, oven=500 if i == 13 else 0)
               for i in range(14)]
        _, state, source, _, events = k.mark_disturbances(rows, obs)
        self.assertEqual((state, source, events), ('active', 'oven', 1))

    def test_floor_model_can_train_after_kitchen_cooling_gap(self):
        rng = random.Random(21)
        rows, observations, room, stored = [], [], 20.0, 0.0
        for i in range(1000):
            heating = float(i % 110 < 55)
            outside = 5 + rng.random() * 4
            oven = 800 if 600 <= i < 606 else 0
            rows.append((i * k.STEP, room, outside, heating, 0.0))
            observations.append(k.KitchenObservation(i * k.STEP, room, heating, 0, oven_power=oven))
            stored = 0.95 * stored + 0.05 * heating
            room += .012 * (outside - room) + .38 * stored + (0.25 if oven else 0)
        masked, state, _, excluded, events = k.mark_disturbances(rows, observations)
        self.assertEqual(state, 'none')
        self.assertEqual(events, 1)
        self.assertGreater(excluded, 6)
        model, status, _ = m.train(masked, 'floor')
        self.assertIsNotNone(model)
        self.assertIn(status, ('ready', 'ready_solar'))

    def test_filtered_dataset_remains_trainable(self):
        rng = random.Random(15)
        rows, observations, room = [], [], 20.0
        for i in range(900):
            heating = float(i % 100 < 50)
            outside = 3 + rng.random() * 4
            oven = 1200 if 400 <= i < 404 else 0
            rows.append((i * k.STEP, room, outside, heating, 0.0))
            observations.append(k.KitchenObservation(i * k.STEP, room, heating, 0, oven_power=oven))
            room += 0.015 * (outside - room) + 0.32 * heating + (0.4 if oven else 0)
        cleaned, status, _, excluded, events = k.mark_disturbances(rows, observations)
        self.assertEqual(status, 'none')
        self.assertEqual(events, 1)
        self.assertGreaterEqual(excluded, 10)
        model, status, _ = m.train(cleaned, 'radiator')
        self.assertIsNotNone(model)
        self.assertIn(status, ('ready', 'ready_solar'))


if __name__ == '__main__':
    unittest.main()
