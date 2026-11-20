"""Initial setup and editable options for Heating Intelligence."""
import voluptuous as vol
from homeassistant.core import callback
from homeassistant import config_entries
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig, SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .settings import (KITCHEN_INPUTS, WINDOW_AZIMUTHS, effective_config,
                       update_floor, update_room, update_sources)

DOMAIN = 'heating_intelligence'


def entity(domain, multiple=False):
    return EntitySelector(EntitySelectorConfig(domain=domain, multiple=multiple))


class HeatingIntelligenceFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HeatingOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input:
            zones = user_input['zones']
            if not zones or len(zones) != len(set(zones)):
                errors['zones'] = 'invalid_zones'
            else:
                self._sources = user_input
                return await self.async_step_floor()
        return self.async_show_form(step_id='user', errors=errors, data_schema=vol.Schema({
            vol.Required('zones'): entity('climate', True),
            vol.Required('outdoor'): entity('sensor'),
            vol.Required('supply'): entity('sensor'),
            vol.Required('return'): entity('sensor'),
            vol.Required('boiler'): entity(['sensor', 'binary_sensor', 'switch']),
            vol.Optional('mixed'): entity('sensor'),
            vol.Optional('irradiance'): entity('sensor'),
            vol.Optional('illuminance'): entity('sensor'),
            vol.Optional('pv_power'): entity('sensor'),
        }))

    async def async_step_floor(self, user_input=None):
        if user_input is not None:
            floor = user_input.get('floor', [])
            if not set(floor).issubset(set(self._sources['zones'])):
                return self.async_show_form(step_id='floor', errors={'floor': 'invalid_zones'},
                                             data_schema=self._floor_schema())
            self._floor = floor
            self._orientations = {}
            self._profiles = {}
            self._orientation_step = 0
            return await self.async_step_orientation()
        return self.async_show_form(step_id='floor', data_schema=self._floor_schema())

    def _floor_schema(self):
        return vol.Schema({vol.Optional('floor', default=[]): EntitySelector(
            EntitySelectorConfig(domain='climate', multiple=True, include_entities=self._sources['zones']))})

    async def async_step_orientation(self, user_input=None):
        """Configure orientation and optional room-specific Kitchen profile."""
        zone = self._sources['zones'][self._orientation_step]
        if user_input is not None:
            directions = user_input.get('windows', ['none'])
            mapping = {'north': 0, 'east': 90, 'south': 180, 'west': 270}
            self._orientations[zone] = {
                'azimuths': [mapping[d] for d in directions if d in mapping],
                'shading': user_input.get('shading', 0) / 100,
            }
            profile = user_input.get('room_profile', 'standard')
            self._profiles[zone] = {
                'type': profile,
                **({key: user_input[key] for key in (
                    'oven_power', 'hob_power', 'hood', 'kitchen_humidity')
                    if profile == 'kitchen' and user_input.get(key)}),
            }
            self._orientation_step += 1
            if self._orientation_step >= len(self._sources['zones']):
                await self.async_set_unique_id('main_heating_system')
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title='Heating Intelligence', data={
                    **self._sources, 'floor': self._floor,
                    'orientations': self._orientations, 'profiles': self._profiles})
            zone = self._sources['zones'][self._orientation_step]
        return self.async_show_form(step_id='orientation', description_placeholders={'zone': zone},
            data_schema=vol.Schema({
                vol.Optional('room_profile', default='standard'): SelectSelector(SelectSelectorConfig(
                    options=['standard', 'kitchen'], mode=SelectSelectorMode.DROPDOWN)),
                vol.Optional('windows', default=['none']): SelectSelector(SelectSelectorConfig(
                    options=['none', 'north', 'east', 'south', 'west'], multiple=True,
                    mode=SelectSelectorMode.DROPDOWN)),
                vol.Optional('shading', default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Optional('oven_power'): entity('sensor'),
                vol.Optional('hob_power'): entity('sensor'),
                vol.Optional('hood'): entity(['binary_sensor', 'switch']),
                vol.Optional('kitchen_humidity'): entity('sensor'),
            }))


class HeatingOptionsFlow(config_entries.OptionsFlowWithReload):
    """Edit existing config without deleting the integration."""

    def _current(self):
        return effective_config(self.config_entry.data, self.config_entry.options)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init",
                                    menu_options=["sources", "floor", "select_room"])

    async def async_step_sources(self, user_input=None):
        current = self._current()
        errors = {}
        if user_input is not None:
            try:
                updated = update_sources(current, user_input)
            except ValueError as exc:
                errors["base"] = str(exc)
            else:
                return self.async_create_entry(data=updated)
        schema = vol.Schema({
            vol.Required("zones"): entity("climate", True),
            vol.Required("outdoor"): entity("sensor"),
            vol.Required("supply"): entity("sensor"),
            vol.Required("return"): entity("sensor"),
            vol.Required("boiler"): entity(["sensor", "binary_sensor", "switch"]),
            vol.Optional("mixed"): entity("sensor"),
            vol.Optional("irradiance"): entity("sensor"),
            vol.Optional("illuminance"): entity("sensor"),
            vol.Optional("pv_power"): entity("sensor"),
        })
        return self.async_show_form(
            step_id="sources", errors=errors,
            data_schema=self.add_suggested_values_to_schema(schema, current))

    async def async_step_floor(self, user_input=None):
        current = self._current()
        errors = {}
        if user_input is not None:
            try:
                updated = update_floor(current, user_input.get("floor", []))
            except ValueError as exc:
                errors["base"] = str(exc)
            else:
                return self.async_create_entry(data=updated)
        schema = vol.Schema({
            vol.Optional("floor"): EntitySelector(EntitySelectorConfig(
                domain="climate", multiple=True,
                include_entities=current["zones"]))
        })
        return self.async_show_form(
            step_id="floor", errors=errors,
            data_schema=self.add_suggested_values_to_schema(schema, current))

    async def async_step_select_room(self, user_input=None):
        current = self._current()
        if user_input is not None:
            self._zone = user_input["zone"]
            if self._zone not in current["zones"]:
                return self.async_show_form(
                    step_id="select_room", errors={"base": "invalid_zone"},
                    data_schema=self._room_selection_schema(current))
            return await self.async_step_room()
        return self.async_show_form(
            step_id="select_room", data_schema=self._room_selection_schema(current))

    def _room_selection_schema(self, current):
        return vol.Schema({
            vol.Required("zone"): SelectSelector(SelectSelectorConfig(
                options=current["zones"], mode=SelectSelectorMode.DROPDOWN))
        })

    async def async_step_room(self, user_input=None):
        current = self._current()
        zone = self._zone
        errors = {}
        if user_input is not None:
            try:
                updated = update_room(current, zone, user_input)
            except ValueError as exc:
                errors["base"] = str(exc)
            else:
                return self.async_create_entry(data=updated)
        orientation = current.get("orientations", {}).get(zone, {})
        profile = current.get("profiles", {}).get(zone, {})
        azimuths = orientation.get("azimuths", [])
        windows = [name for name, azimuth in WINDOW_AZIMUTHS.items()
                   if azimuth in azimuths] or ["none"]
        defaults = {"room_profile": profile.get("type", "standard"),
                    "windows": windows,
                    "shading": round(orientation.get("shading", 0) * 100),
                    **{key: profile[key] for key in KITCHEN_INPUTS if profile.get(key)}}
        schema = vol.Schema({
            vol.Optional("room_profile"): SelectSelector(SelectSelectorConfig(
                options=["standard", "kitchen"], mode=SelectSelectorMode.DROPDOWN)),
            vol.Optional("windows"): SelectSelector(SelectSelectorConfig(
                options=["none", "north", "east", "south", "west"],
                multiple=True, mode=SelectSelectorMode.DROPDOWN)),
            vol.Optional("shading"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
            vol.Optional("oven_power"): entity("sensor"),
            vol.Optional("hob_power"): entity("sensor"),
            vol.Optional("hood"): entity(["binary_sensor", "switch"]),
            vol.Optional("kitchen_humidity"): entity("sensor"),
        })
        return self.async_show_form(
            step_id="room", description_placeholders={"zone": zone},
            errors=errors,
            data_schema=self.add_suggested_values_to_schema(schema, defaults))
