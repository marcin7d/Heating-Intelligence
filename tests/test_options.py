"""Editable options and per-zone model invalidation, without HA dependency."""
import importlib.util
from pathlib import Path
import sys
import unittest

path = (Path(__file__).resolve().parents[1] /
        "custom_components/heating_intelligence/settings.py")
spec = importlib.util.spec_from_file_location("hi_editable_settings", path)
s = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = s
spec.loader.exec_module(s)

BASE = {"zones": ["climate.a", "climate.b", "climate.c"],
        "outdoor": "sensor.out", "supply": "sensor.supply",
        "return": "sensor.return", "boiler": "binary_sensor.boiler",
        "irradiance": "sensor.solar", "floor": ["climate.a"],
        "profiles": {"climate.a": {"type": "standard"},
                     "climate.b": {"type": "kitchen", "oven_power": "sensor.oven"}},
        "orientations": {"climate.a": {"azimuths": [180], "shading": .2}}}


class ConfigOptionsTests(unittest.TestCase):
    def test_options_override_without_mutating_entry_data(self):
        cfg = s.effective_config(BASE, {"return": "sensor.new_return"})
        self.assertEqual(cfg["return"], "sensor.new_return")
        self.assertEqual(BASE["return"], "sensor.return")

    def test_sources_preserve_unmodified_rooms(self):
        submitted = {k: BASE[k] for k in s.REQUIRED}
        submitted["zones"] = ["climate.a", "climate.c", "climate.d"]
        result = s.update_sources(BASE, submitted)
        self.assertNotIn("irradiance", result)
        self.assertNotIn("climate.b", result["profiles"])
        self.assertEqual(result["floor"], ["climate.a"])
        self.assertEqual(result["orientations"]["climate.a"]["shading"], .2)
        self.assertEqual(result["zones"][-1], "climate.d")

    def test_floor_subset_validation(self):
        with self.assertRaises(ValueError):
            s.update_floor(BASE, ["climate.missing"])
        self.assertEqual(s.update_floor(BASE, [])["floor"], [])

    def test_room_edit_selectively_updates_profile(self):
        after = s.update_room(BASE, "climate.a", {
            "room_profile": "kitchen", "windows": ["east", "west"],
            "shading": 30, "oven_power": "sensor.new_oven"})
        self.assertEqual(after["profiles"]["climate.b"], BASE["profiles"]["climate.b"])
        self.assertEqual(after["profiles"]["climate.a"]["oven_power"], "sensor.new_oven")
        self.assertEqual(after["orientations"]["climate.a"]["azimuths"], [90, 270])

    def test_reuse_models_except_for_changed_inputs(self):
        after = s.update_room(BASE, "climate.b", {"room_profile": "standard"})
        after["return"] = "sensor.new_return"
        self.assertEqual(s.training_signature(BASE, "climate.a"),
                         s.training_signature(after, "climate.a"))
        self.assertNotEqual(s.training_signature(BASE, "climate.b"),
                            s.training_signature(after, "climate.b"))
        floor_changed = s.update_floor(BASE, ["climate.a", "climate.c"])
        self.assertNotEqual(s.training_signature(BASE, "climate.c"),
                            s.training_signature(floor_changed, "climate.c"))
        self.assertIsNone(s.training_signature(BASE, "climate.missing"))


if __name__ == "__main__":
    unittest.main()
