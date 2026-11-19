# Heating Intelligence 0.1.1

[Polish documentation](README.md)

Read-only Home Assistant Core 2026.11 integration for any positive number of heating zones. It learns how each room responds and exposes forecasts and boiler advice. Existing heating controls operate independently.

## Installation

Extract the ZIP and copy `custom_components/heating_intelligence` into Home Assistant's `/config/custom_components/`. Restart Home Assistant and choose **Settings → Devices & services → Add integration → Heating Intelligence**. Select one or more distinct climate entities, outdoor temperature, boiler supply and return temperature, boiler activity, and optionally mixed floor supply temperature. Select floor zones in the second step. Remaining zones are treated as radiators.

You can also add this public repository through Home Assistant Marketplace: https://github.com/marcin7d/Heating-Intelligence .

## Data and outputs

- Recorder must include the selected entities and climate attributes. The integration reads up to seven days of history. It uses `hvac_action` where available and can infer demand from a deficit of at least 0.3°C in heating-capable modes with a single setpoint.
- Select actual space-heating burner activity for burner cycle metrics. A relay signal measures demand cycles. A signal that includes domestic hot water will include those cycles. Supported state pairs are `on/off`, `1/0`, `1.0/0.0`, `true/false`, and `heating/idle`. State `running` is also accepted.
- System sensors show boiler ΔT in kelvin, starts since local midnight, runtime, mean completed cycle duration, history coverage, and boiler advice. Thermal power additionally requires flow measurement.
- Zone sensors show temperature in 30, 60, 120, and 360 minutes under constant current conditions. Preheat lead time uses the current setpoint and estimated active heat input. Apply it relative to the intended comfort time.
- Radiators use boiler supply temperature. Floor zones use mixed supply temperature if configured and boiler activity as a proxy otherwise. Adjusting the mixer changes thermal behavior when mixed temperature is unmeasured.
- Results refresh every five minutes. Bounded thermal models are saved locally. Training requires both heating and low-input periods. The final 20% of samples selects the model and checks five-minute error against persistence. Predictions are withheld when inputs or results are insufficient.
- The advisory demand score sums active zones' temperature deficits with a cap of one point per zone. The recommendation reflects overall demand, priority for a large single-zone deficit, and recent starts. It makes no changes to the equipment.

Run `python -m unittest discover -s tests -v` for unit tests. GitHub Actions also defines a Core 2026.11.0 smoke test. **Experimental; not yet verified on the physical installation.**
