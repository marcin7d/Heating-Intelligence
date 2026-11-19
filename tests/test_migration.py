"""Test config-entry and model-storage migrations without live HA."""
import ast
import asyncio
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'custom_components' / 'heating_intelligence' / '__init__.py'
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
fn = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'async_migrate_entry')
ns = {}
exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SOURCE), 'exec'), ns)
migrate = ns['async_migrate_entry']

class Entry:
    def __init__(self, version):
        self.version = version
        self.data = {'zones': ['climate.salon_thermostat'], 'outdoor': 'sensor.outdoor'}

class ConfigEntries:
    def __init__(self):
        self.calls = 0
    def async_update_entry(self, entry, *, data, version):
        self.calls += 1
        entry.data = data
        entry.version = version

class Hass:
    def __init__(self):
        self.config_entries = ConfigEntries()

class TestMigration(unittest.TestCase):
    def test_v1_upgrades_preserving_sources(self):
        hass, entry = Hass(), Entry(1)
        self.assertTrue(asyncio.run(migrate(hass, entry)))
        self.assertEqual(entry.version, 2)
        self.assertEqual(entry.data['zones'], ['climate.salon_thermostat'])
        self.assertEqual(entry.data['outdoor'], 'sensor.outdoor')
        self.assertEqual(entry.data['profiles'], {})
        self.assertEqual(entry.data['orientations'], {})
        self.assertEqual(hass.config_entries.calls, 1)

    def test_v2_noop(self):
        hass, entry = Hass(), Entry(2)
        self.assertTrue(asyncio.run(migrate(hass, entry)))
        self.assertEqual(hass.config_entries.calls, 0)

    def test_future_version_not_accepted(self):
        hass, entry = Hass(), Entry(3)
        self.assertFalse(asyncio.run(migrate(hass, entry)))

COORDINATOR = SOURCE.with_name('coordinator.py')
coord_tree = ast.parse(COORDINATOR.read_text(encoding='utf-8'))
store_class = next(node for node in coord_tree.body if isinstance(node, ast.ClassDef) and node.name == 'HeatingModelStore')
store_method = next(node for node in store_class.body if isinstance(node, ast.AsyncFunctionDef) and node.name == '_async_migrate_func')
store_code = compile(ast.Module(body=[store_method], type_ignores=[]), str(COORDINATOR), 'exec')
store_ns = {}
exec(store_code, store_ns)

class TestModelStorageMigration(unittest.TestCase):
    def test_v1_model_storage_converts(self):
        old = {'config': {'zones': ['climate.salon']}, 'models': {'climate.salon': {'memory': 0.5}}, 'trained': 100}
        new = asyncio.run(store_ns['_async_migrate_func'](None, 1, 1, old))
        self.assertEqual(new['config'], old['config'])
        self.assertEqual(new['models'], {})
        self.assertEqual(new['last_training'], 0)
        self.assertEqual(new['diagnostics'], {})

    def test_unknown_storage_version_rejected(self):
        with self.assertRaises(NotImplementedError):
            asyncio.run(store_ns['_async_migrate_func'](None, 3, 1, {}))
