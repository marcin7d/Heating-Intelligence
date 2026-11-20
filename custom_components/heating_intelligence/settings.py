"""Pure helpers for editable Heating Intelligence settings and model compatibility."""

REQUIRED = ("zones", "outdoor", "supply", "return", "boiler")
OPTIONAL = ("mixed", "irradiance", "illuminance", "pv_power")
WINDOW_AZIMUTHS = {"north": 0, "east": 90, "south": 180, "west": 270}
KITCHEN_INPUTS = ("oven_power", "hob_power", "hood", "kitchen_humidity")


def effective_config(entry_data, entry_options):
    """Stored options represent a complete editable configuration."""
    return dict(entry_options) if entry_options else dict(entry_data)


def update_sources(current, submitted):
    """Edit entities, preserving settings for unchanged zones."""
    zones = list(submitted.get("zones", ()))
    if not zones or len(set(zones)) != len(zones):
        raise ValueError("invalid_zones")
    if any(not submitted.get(k) for k in REQUIRED if k != "zones"):
        raise ValueError("missing_required_source")
    updated = dict(current)
    updated["zones"] = zones
    for key in (*REQUIRED[1:], *OPTIONAL):
        if submitted.get(key):
            updated[key] = submitted[key]
        else:
            updated.pop(key, None)
    updated["floor"] = [z for z in current.get("floor", ()) if z in zones]
    updated["profiles"] = {z: dict(v) for z, v in current.get("profiles", {}).items()
                           if z in zones}
    updated["orientations"] = {z: dict(v) for z, v in current.get("orientations", {}).items()
                               if z in zones}
    return updated


def update_floor(current, selected):
    zones = set(current["zones"])
    if len(set(selected)) != len(selected) or not set(selected).issubset(zones):
        raise ValueError("invalid_floor")
    return {**current, "floor": list(selected)}


def update_room(current, zone, submitted):
    if zone not in current["zones"]:
        raise ValueError("invalid_zone")
    directions = submitted.get("windows", ["none"])
    azimuths = [WINDOW_AZIMUTHS[d] for d in directions if d in WINDOW_AZIMUTHS]
    shading = int(submitted.get("shading", 0))
    if not 0 <= shading <= 100:
        raise ValueError("invalid_shading")
    kind = submitted.get("room_profile", "standard")
    if kind not in ("standard", "kitchen"):
        raise ValueError("invalid_profile")
    updated = dict(current)
    updated["orientations"] = {**current.get("orientations", {}),
                               zone: {"azimuths": azimuths, "shading": shading / 100}}
    profile = {"type": kind}
    if kind == "kitchen":
        profile.update({key: submitted[key] for key in KITCHEN_INPUTS if submitted.get(key)})
    updated["profiles"] = {**current.get("profiles", {}), zone: profile}
    return updated


def training_signature(config, zone):
    """Changes to only the relevant input signals invalidate a zone model."""
    if zone not in config.get("zones", ()):
        return None
    floor = zone in config.get("floor", ())
    orientation = config.get("orientations", {}).get(zone, {})
    profile = config.get("profiles", {}).get(zone, {})
    return (
        config.get("outdoor"),
        config.get("boiler"),
        config.get("mixed") if floor else config.get("supply"),
        config.get("supply") if floor and not config.get("mixed") else None,
        floor,
        *(config.get(key) for key in ("irradiance", "illuminance", "pv_power")),
        tuple(orientation.get("azimuths", ())),
        orientation.get("shading", 0),
        profile.get("type", "standard"),
        *(profile.get(key) for key in KITCHEN_INPUTS),
    )
