"""Collect boiler entities and a variable-size zone mapping."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig


def selector(domains, multiple=False):
    return EntitySelector(EntitySelectorConfig(domain=domains, multiple=multiple))


class HeatingFlow(config_entries.ConfigFlow, domain="heating_intelligence"):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            zones = user_input["zones"]
            if not zones:
                errors["zones"] = "at_least_one_zone"
            elif len(set(zones)) != len(zones):
                errors["zones"] = "duplicate_zones"
            elif len({user_input[key] for key in ("outdoor", "supply", "return", "boiler", "mixed") if key in user_input}) != len([key for key in ("outdoor", "supply", "return", "boiler", "mixed") if key in user_input]):
                errors["base"] = "duplicate_sources"
            else:
                self.sources = user_input
                return await self.async_step_floor()
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required("zones"): selector("climate", True),
            vol.Required("outdoor"): selector("sensor"),
            vol.Required("supply"): selector("sensor"),
            vol.Required("return"): selector("sensor"),
            vol.Required("boiler"): selector(["binary_sensor", "sensor", "switch"]),
            vol.Optional("mixed"): selector("sensor"),
        }))

    async def async_step_floor(self, user_input=None):
        errors = {}
        if user_input is not None:
            floor = user_input.get("floor", [])
            if not set(floor) <= set(self.sources["zones"]):
                errors["floor"] = "floor_subset"
            else:
                await self.async_set_unique_id("heating_system")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Heating Intelligence", data={**self.sources, "floor": floor})
        return self.async_show_form(step_id="floor", errors=errors, data_schema=vol.Schema({
            vol.Optional("floor", default=[]): EntitySelector(
                EntitySelectorConfig(domain="climate", multiple=True, include_entities=self.sources["zones"])
            )
        }))
