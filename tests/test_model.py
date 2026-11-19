import importlib.util
from pathlib import Path
import random
import sys
import unittest

spec = importlib.util.spec_from_file_location(
    "thermal_model", Path(__file__).resolve().parents[1] /
    "custom_components/heating_intelligence/model.py",
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class Models(unittest.TestCase):
    def test_units_and_invalid(self):
        self.assertEqual(m.temperature(68, "°F"), 20)
        self.assertIsNone(m.temperature("unknown"))
        self.assertIsNone(m.temperature("inf"))

    def test_floor_does_not_use_boiler_temperature(self):
        self.assertEqual(m.heat("floor", True, True, 20, 65, None), 1)
        self.assertEqual(m.heat("floor", True, False, 20, 65, 35), 1)
        self.assertIsNone(m.heat("floor", True, None, 20, 65, None))
        self.assertEqual(m.heat("radiator", True, True, 20, 65, None), 1.5)

    def test_learning_floor_and_radiator(self):
        for kind, memory in (("floor", 0.95), ("radiator", 0.0)):
            with self.subTest(kind=kind):
                rng = random.Random(15)
                rows, room, mass = [], 20, 0
                for i in range(900):
                    power = float(i % 90 < 45)
                    outside = 3 + rng.random() * 4
                    rows.append((i * m.STEP, room, outside, power))
                    mass = memory * mass + (1 - memory) * power
                    room += 0.012 * (outside - room) + 0.38 * mass
                model = m.fit(rows, kind)
                self.assertIsNotNone(model)
                self.assertEqual(model.memory, memory)
                self.assertLess(model.error, model.baseline)
                temperatures, lead = m.forecast(model, rows, 5, 0, rows[-1][1] + 1, 1)
                self.assertEqual(set(temperatures), set(m.HORIZONS))
                self.assertIsNotNone(lead)

    def test_no_model_without_heating_cycles(self):
        self.assertIsNone(m.fit([(i * m.STEP, 20, 5, 0) for i in range(600)], "floor"))

    def test_gap_blocks_inertia_prediction(self):
        model = m.Model(0.95, 0.012, 0.3, 0, 0.01, 0.03, 500)
        self.assertEqual(m.forecast(model, [(0, 20, 5, 1), (900, 20, 5, 1)], 5, 1, 21, 1), ({}, None))

    def test_boiler_clips_midnight_and_excludes_unknown(self):
        events = [(-60, True), (60, False), (120, True), (240, False), (300, None)]
        self.assertEqual(m.cycles(events, 0, 600), {"starts": 1, "runtime": 3, "cycle": 2, "coverage": 50})

    def test_advice_only_counts_requesting_zones(self):
        self.assertEqual(m.demand([(False, 3), (True, 0.8)], False, None, 2000), (0.8, "consider_heat"))
        self.assertEqual(m.demand([(None, None)], False, None, 2000), (None, "insufficient_data"))


if __name__ == "__main__":
    unittest.main()
