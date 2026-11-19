# Heating Intelligence 0.2.1 — unpublished development draft

Read-only Home Assistant 2026.11 custom integration. Supports any positive number of climate zones, radiator and underfloor heating, boiler supply and return temperature, optional mixed-floor supply and three **optional** solar signal sources: irradiance W/m², illuminance lux and PV power W. Configure window orientation and approximate shading independently for each zone.

Irradiance is preferred; lux and PV are proxy features, not physical equivalents. Solar irradiance is **not** added to lux or PV. A sunlight-augmented model is selected only when its holdout five-minute error improves by at least 3% against the base thermal model. Diagnostic sensors expose model status, sample count, short-horizon validation MAE and sunlight-model details.

Heating predictions cover 30, 60, 120 and 360 minutes. The six-hour forecast assumes current conditions persist and does not incorporate a future irradiance forecast. Recorder is queried for up to seven days. There is no direct control of climate, boiler or mixer. This draft has no automated migration from version 0.1.1; use a staging Home Assistant installation.

Unit tests: `python -m unittest discover -s tests -v`. **Not yet integration-tested against a live Home Assistant 2026.11 instance.** The code has intentionally **not** been published to GitHub.

## New Kitchen room profile (unpublished draft)

During each zone's UI setup, choose `Room profile: kitchen` independently of radiator/floor heating. Optionally select oven and hob **power** sensors (W or kW), extractor hood state (`binary_sensor`/`switch`), and indoor kitchen humidity (%). Leaving all four optional is supported.

Non-heating disturbances are detected using oven or hob power **≥150 W**, an active extractor, a humidity jump of **≥6 percentage points per five minutes**, or unexpected warming of **≥0.25°C per five minutes when both measured heat delivery and sunlight are low**. Event periods and the next **30 minutes** are excluded from thermal-model training. Existing Recorder data is not deleted.

While cooking heat is detected or in cooldown, kitchen temperature forecasts and preheat recommendations are temporarily withheld because the model does not predict appliance or cooking heat. Other rooms are not affected. Learned kitchen coefficients are retained. New diagnostic sensors: `Room profile`, `Kitchen internal heat`, `Kitchen heat source`, `Kitchen training samples excluded`, and `Kitchen heat events in training window`.

**Limitations:** The system identifies disturbances; it does not measure actual cooking heat or predict when someone will cook. Extractor activity may be ventilation without cooking. Slow internal gains may be missed. Temperature-only detection requires valid low-sunlight and low-heating evidence. Thresholds are experimental and should be validated in an actual installation. Changing the profile of an existing configured installation currently requires removing and re-adding the integration; back up first. No changes are published to GitHub in this draft.

## Missing forecast diagnostics — unpublished 0.2.1 draft

Each configured zone reports **Model training status**, **Model valid history rows**, **Model missing room/outdoor/heat rows**, **Model heating samples**, **Model idle samples**, **Model temperature changes**, **Model candidate validation MAE**, **Model constant-temperature baseline MAE**, and **Last model training attempt (Unix UTC)**. Statuses distinguish `insufficient_valid_samples`, `insufficient_heating_samples`, `insufficient_idle_samples`, `no_temperature_variation`, and `validation_failed`. Training retries hourly until every configured zone has an accepted model. Models are not forced through validation.

This is an unpublished draft with unit tests only, not a validated installation on a production Home Assistant instance. Back up the installation before replacing the files. Existing config entries do not automatically gain new config-flow options.

## Upgrade from 0.1.1

Version 0.2.1 migrates version-1 config entries to version 2 without removing selected zones or sensor sources. Old model coefficients are incompatible with the new model and are retrained. Existing entries do not yet expose the new solar/kitchen setup through an options flow. Restart Home Assistant Core after updating.
