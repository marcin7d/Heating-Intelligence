"""Run against real Home Assistant Core with an in-memory entity fixture."""
import asyncio
import inspect
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant, State
from custom_components.heating_intelligence.config_flow import HeatingFlow
from custom_components.heating_intelligence.coordinator import calculate
from custom_components.heating_intelligence.sensor import HeatingSensor


async def main():
    hass = HomeAssistant("/tmp")
    flow = HeatingFlow()
    flow.hass = hass
    assert (await flow.async_step_user())["type"] == "form"
    zones = [f"climate.zone_{i}" for i in range(3)]
    config = {"zones": zones, "outdoor": "sensor.outdoor", "supply": "sensor.supply",
              "return": "sensor.return", "boiler": "binary_sensor.burner"}
    assert (await flow.async_step_user(config))["step_id"] == "floor"
    config["floor"] = zones[:1]
    states = {zone: State(zone, "heat", {"current_temperature": 20, "temperature": 21,
                                       "hvac_action": "heating"}) for zone in zones}
    states.update({"sensor.outdoor": State("sensor.outdoor", "5"),
                   "sensor.supply": State("sensor.supply", "55"),
                   "sensor.return": State("sensor.return", "40"),
                   "binary_sensor.burner": State("binary_sensor.burner", "on")})
    now = int(datetime.now(timezone.utc).timestamp())
    result, _ = calculate(config, {}, states, "°C", now, now - 3600, {}, False, False)
    assert result["delta_t"] == 15 and result["demand"] == 3
    assert len(result["zones"]) == 3
    assert "significant_changes_only" in inspect.signature(get_significant_states).parameters
    assert HeatingSensor is not None


asyncio.run(main())
