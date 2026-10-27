"""Vehicle Service Manager integration (US edition)."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_state_change_event
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN, PLATFORMS, CONFIG_VERSION, KM_PER_MILE,
    CONF_MAKE, CONF_MODEL, CONF_YEAR, CONF_IN_SERVICE_DATE, CONF_ODOMETER,
    CONF_PLATE, CONF_VIN, CONF_ODOMETER_ENTITY, CONF_SERVICES, CONF_INTERVALS,
    CONF_LAST_INSPECTION_DATE, CONF_LAST_INSPECTION_ODOMETER, CONF_REGISTRATION_EXPIRES,
    CONF_SCHEDULE, CONF_SEVERE, CONF_ENGINE, CONF_TRANSMISSION, CONF_FUEL,
    ALL_SERVICE_IDS, REPAIR_CATEGORIES, TIRE_POSITIONS,
    SERVICE_STATE_INSPECTION, SERVICE_REGISTRATION,
    HA_SERVICE_ADD_ENTRY, HA_SERVICE_UPDATE_ODOMETER,
    HA_SERVICE_ADD_REPAIR, HA_SERVICE_ADD_TIRE,
)
from .helpers import add_months, parse_date
from .store import get_store, VehicleServiceStore

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entries from the original metric integration can't be migrated."""
    if entry.version < CONFIG_VERSION:
        _LOGGER.error(
            "Vehicle '%s' was created by the original (metric) Vehicle Service "
            "Manager and can't be migrated. Delete it and add the vehicle again.",
            entry.title,
        )
        return False
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one vehicle from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    store = get_store(hass)
    await store.async_load()

    vehicle_id: str = entry.data["vehicle_id"]

    if store.get_vehicle(vehicle_id) is None:
        _LOGGER.info("Creating new vehicle %s in store", vehicle_id)
        await store.async_add_vehicle(vehicle_id, _build_initial_vehicle(entry.data))
        await _seed_initial_entries(store, vehicle_id, entry.data)
    else:
        # Keep store in sync with edits made in the options flow
        await store.async_update_vehicle(vehicle_id, _vehicle_settings(entry.data))

    hass.data[DOMAIN][entry.entry_id] = {"vehicle_id": vehicle_id}
    _remove_stale_entities(hass, entry, vehicle_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.data[DOMAIN].get("_api_registered"):
        _register_websocket(hass)
        _register_services(hass)
        hass.data[DOMAIN]["_api_registered"] = True

    entity_id: str = (entry.data.get(CONF_ODOMETER_ENTITY) or "").strip()
    if entity_id:
        _setup_odometer_tracking(hass, entry, store, vehicle_id, entity_id)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up store data when a config entry (vehicle) is deleted."""
    vehicle_id: str = entry.data.get("vehicle_id", "")
    if not vehicle_id:
        return
    store = get_store(hass)
    await store.async_load()
    if store.get_vehicle(vehicle_id) is not None:
        await store.async_remove_vehicle(vehicle_id)
        _LOGGER.info("Vehicle %s removed from store after entry deletion", vehicle_id)


def _remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry, vehicle_id: str) -> None:
    """Drop entities for service items that were deselected in options."""
    selected = set(entry.data.get(CONF_SERVICES, []))
    registry = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        for svc_id in ALL_SERVICE_IDS:
            if svc_id not in selected and ent.unique_id in (
                f"{vehicle_id}_{svc_id}_status", f"{vehicle_id}_{svc_id}_due"
            ):
                registry.async_remove(ent.entity_id)


# ── Vehicle dict ──────────────────────────────────────────────────────────────

def _vehicle_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Fields owned by the config entry (editable in options)."""
    return {
        "make":          data.get(CONF_MAKE, ""),
        "model":         data.get(CONF_MODEL, ""),
        "year":          data.get(CONF_YEAR),
        "inServiceDate": data.get(CONF_IN_SERVICE_DATE),
        "plate":         data.get(CONF_PLATE, ""),
        "vin":           data.get(CONF_VIN, ""),
        "entity":        data.get(CONF_ODOMETER_ENTITY, ""),
        "services":      data.get(CONF_SERVICES, []),
        "intervals":     data.get(CONF_INTERVALS, {}),
        "scheduleId":    data.get(CONF_SCHEDULE),
        "severe":        data.get(CONF_SEVERE, False),
        "engine":        data.get(CONF_ENGINE),
        "transmission":  data.get(CONF_TRANSMISSION),
        "fuel":          data.get(CONF_FUEL),
    }


def _build_initial_vehicle(data: dict[str, Any]) -> dict[str, Any]:
    odometer = int(data.get(CONF_ODOMETER) or 0)
    return {
        **_vehicle_settings(data),
        "odometer":      odometer,
        "startOdometer": odometer,   # basis for cost per mile
        "lastService":   {},
        "history":       [],
        "repairs":       [],
        "tires":         [],
    }


async def _seed_initial_entries(
    store: VehicleServiceStore, vehicle_id: str, data: dict[str, Any]
) -> None:
    services = data.get(CONF_SERVICES, [])
    insp_date = data.get(CONF_LAST_INSPECTION_DATE)
    if insp_date and SERVICE_STATE_INSPECTION in services:
        await store.async_add_service_entry(
            vehicle_id=vehicle_id, entry_date=insp_date,
            odometer=int(data.get(CONF_LAST_INSPECTION_ODOMETER) or 0),
            services=[SERVICE_STATE_INSPECTION],
            notes="Entered during vehicle setup", auto=True,
        )
    reg_expires = parse_date(data.get(CONF_REGISTRATION_EXPIRES))
    months = (data.get(CONF_INTERVALS, {}).get(SERVICE_REGISTRATION) or {}).get("months")
    if reg_expires and months and SERVICE_REGISTRATION in services:
        # Logged as the last renewal: expiration minus the renewal interval
        await store.async_add_service_entry(
            vehicle_id=vehicle_id,
            entry_date=add_months(reg_expires, -months).isoformat(), odometer=0,
            services=[SERVICE_REGISTRATION],
            notes="Entered during vehicle setup", auto=True,
        )


# ── Live odometer tracking ────────────────────────────────────────────────────

def _state_to_miles(state) -> int | None:
    try:
        value = float(state.state)
    except (ValueError, TypeError):
        return None
    unit = (state.attributes.get("unit_of_measurement") or "").lower()
    if unit == "km":
        value = value / KM_PER_MILE
    return int(round(value))


def _setup_odometer_tracking(
    hass: HomeAssistant, entry: ConfigEntry, store: VehicleServiceStore,
    vehicle_id: str, entity_id: str,
) -> None:
    @callback
    def _on_state_change(event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        miles = _state_to_miles(new_state)
        if miles is not None and miles > 0:
            hass.async_create_task(store.async_update_odometer(vehicle_id, miles))

    entry.async_on_unload(
        async_track_state_change_event(hass, [entity_id], _on_state_change)
    )

    state = hass.states.get(entity_id)
    if state is not None:
        miles = _state_to_miles(state)
        if miles:
            hass.async_create_task(store.async_update_odometer(vehicle_id, miles))
    _LOGGER.debug("Tracking odometer entity %s for vehicle %s", entity_id, vehicle_id)


# ── Shared schemas ────────────────────────────────────────────────────────────

_SERVICE_IDS = vol.All(cv.ensure_list, [vol.In(ALL_SERVICE_IDS)])
_MONEY = vol.All(vol.Coerce(float), vol.Range(min=0))
_TREAD = vol.All(vol.Coerce(float), vol.Range(min=0, max=32))

_ENTRY_FIELDS = {
    vol.Required("entry_date"): cv.string,
    vol.Required("odometer"): vol.Coerce(int),
    vol.Required("services"): _SERVICE_IDS,
    vol.Optional("notes", default=""): cv.string,
    vol.Optional("shop", default=""): cv.string,
    vol.Optional("cost", default=0): _MONEY,
}
_REPAIR_FIELDS = {
    vol.Required("entry_date"): cv.string,
    vol.Required("odometer"): vol.Coerce(int),
    vol.Required("category"): vol.In(list(REPAIR_CATEGORIES)),
    vol.Optional("description", default=""): cv.string,
    vol.Optional("shop", default=""): cv.string,
    vol.Optional("cost", default=0): _MONEY,
}
_TIRE_FIELDS = {
    vol.Required("entry_date"): cv.string,
    vol.Required("odometer"): vol.Coerce(int),
    vol.Required("tire_type"): vol.In(["all_season", "summer", "winter", "all_terrain"]),
    vol.Required("axle"): vol.In(["all", "front", "rear"]),
    vol.Optional("size", default=""): cv.string,
    vol.Optional("brand", default=""): cv.string,
    vol.Optional("model", default=""): cv.string,
    vol.Optional("dot", default=""): cv.string,
    vol.Optional("shop", default=""): cv.string,
    vol.Optional("cost", default=0): _MONEY,
    **{vol.Optional(pos, default=0.0): _TREAD for pos in TIRE_POSITIONS},
}


def _repair_from(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": data["entry_date"], "odometer": data["odometer"],
        "category": data["category"], "description": data.get("description", ""),
        "shop": data.get("shop", ""), "cost": data.get("cost", 0),
    }


def _tire_from(data: dict[str, Any]) -> dict[str, Any]:
    tire = {
        "date": data["entry_date"], "odometer": data["odometer"],
        "type": data["tire_type"], "axle": data["axle"],
        "size": data.get("size", ""), "brand": data.get("brand", ""),
        "model": data.get("model", ""), "dot": data.get("dot", ""),
        "shop": data.get("shop", ""), "cost": data.get("cost", 0),
    }
    for pos in TIRE_POSITIONS:
        tire[pos] = data.get(pos, 0.0)
    return tire


# ── WebSocket API (used by the dashboard card) ────────────────────────────────

def _register_websocket(hass: HomeAssistant) -> None:

    def _vehicle_or_error(connection, msg) -> dict | None:
        vehicle = get_store(hass).get_vehicle(msg["vehicle_id"])
        if vehicle is None:
            connection.send_error(msg["id"], "not_found", f"Vehicle {msg['vehicle_id']} not found")
        return vehicle

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/vehicles"})
    @websocket_api.async_response
    async def ws_get_vehicles(hass, connection, msg):
        store = get_store(hass)
        await store.async_load()
        connection.send_result(msg["id"], {"vehicles": store.get_vehicles()})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/add_service_entry",
        vol.Required("vehicle_id"): str, **_ENTRY_FIELDS,
    })
    @websocket_api.async_response
    async def ws_add_service_entry(hass, connection, msg):
        if _vehicle_or_error(connection, msg) is None:
            return
        store = get_store(hass)
        entry = await store.async_add_service_entry(
            vehicle_id=msg["vehicle_id"], entry_date=msg["entry_date"],
            odometer=msg["odometer"], services=msg["services"], notes=msg["notes"],
            shop=msg["shop"], cost=msg["cost"],
        )
        connection.send_result(msg["id"], {"entry": entry, "vehicle": store.get_vehicle(msg["vehicle_id"])})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/update_service_entry",
        vol.Required("vehicle_id"): str,
        vol.Required("entry_index"): vol.Coerce(int), **_ENTRY_FIELDS,
    })
    @websocket_api.async_response
    async def ws_update_service_entry(hass, connection, msg):
        if _vehicle_or_error(connection, msg) is None:
            return
        store = get_store(hass)
        try:
            await store.async_update_service_entry(
                vehicle_id=msg["vehicle_id"], entry_index=msg["entry_index"],
                entry_date=msg["entry_date"], odometer=msg["odometer"],
                services=msg["services"], notes=msg["notes"], shop=msg["shop"], cost=msg["cost"],
            )
        except IndexError as err:
            connection.send_error(msg["id"], "invalid_index", str(err))
            return
        connection.send_result(msg["id"], {"vehicle": store.get_vehicle(msg["vehicle_id"])})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/delete_service_entry",
        vol.Required("vehicle_id"): str,
        vol.Required("entry_index"): vol.Coerce(int),
    })
    @websocket_api.async_response
    async def ws_delete_service_entry(hass, connection, msg):
        if _vehicle_or_error(connection, msg) is None:
            return
        store = get_store(hass)
        await store.async_delete_service_entry(msg["vehicle_id"], msg["entry_index"])
        connection.send_result(msg["id"], {"vehicle": store.get_vehicle(msg["vehicle_id"])})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/add_repair",
        vol.Required("vehicle_id"): str, **_REPAIR_FIELDS,
    })
    @websocket_api.async_response
    async def ws_add_repair(hass, connection, msg):
        if _vehicle_or_error(connection, msg) is None:
            return
        store = get_store(hass)
        await store.async_add_repair(msg["vehicle_id"], _repair_from(msg))
        connection.send_result(msg["id"], {"vehicle": store.get_vehicle(msg["vehicle_id"])})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/update_repair",
        vol.Required("vehicle_id"): str,
        vol.Required("repair_index"): vol.Coerce(int), **_REPAIR_FIELDS,
    })
    @websocket_api.async_response
    async def ws_update_repair(hass, connection, msg):
        if _vehicle_or_error(connection, msg) is None:
            return
        store = get_store(hass)
        try:
            await store.async_update_repair(msg["vehicle_id"], msg["repair_index"], _repair_from(msg))
        except IndexError as err:
            connection.send_error(msg["id"], "invalid_index", str(err))
            return
        connection.send_result(msg["id"], {"vehicle": store.get_vehicle(msg["vehicle_id"])})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/delete_repair",
        vol.Required("vehicle_id"): str,
        vol.Required("repair_index"): vol.Coerce(int),
    })
    @websocket_api.async_response
    async def ws_delete_repair(hass, connection, msg):
        if _vehicle_or_error(connection, msg) is None:
            return
        store = get_store(hass)
        await store.async_delete_repair(msg["vehicle_id"], msg["repair_index"])
        connection.send_result(msg["id"], {"vehicle": store.get_vehicle(msg["vehicle_id"])})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/add_tire",
        vol.Required("vehicle_id"): str, **_TIRE_FIELDS,
    })
    @websocket_api.async_response
    async def ws_add_tire(hass, connection, msg):
        if _vehicle_or_error(connection, msg) is None:
            return
        store = get_store(hass)
        await store.async_add_tire(msg["vehicle_id"], _tire_from(msg))
        connection.send_result(msg["id"], {"vehicle": store.get_vehicle(msg["vehicle_id"])})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/delete_tire",
        vol.Required("vehicle_id"): str,
        vol.Required("tire_index"): vol.Coerce(int),
    })
    @websocket_api.async_response
    async def ws_delete_tire(hass, connection, msg):
        if _vehicle_or_error(connection, msg) is None:
            return
        store = get_store(hass)
        await store.async_delete_tire(msg["vehicle_id"], msg["tire_index"])
        connection.send_result(msg["id"], {"vehicle": store.get_vehicle(msg["vehicle_id"])})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/update_odometer",
        vol.Required("vehicle_id"): str,
        vol.Required("odometer"): vol.Coerce(int),
        vol.Optional("allow_decrease", default=False): bool,
    })
    @websocket_api.async_response
    async def ws_update_odometer(hass, connection, msg):
        if _vehicle_or_error(connection, msg) is None:
            return
        await get_store(hass).async_update_odometer(
            msg["vehicle_id"], msg["odometer"], msg["allow_decrease"]
        )
        connection.send_result(msg["id"], {"success": True})

    for fn in [
        ws_get_vehicles, ws_add_service_entry, ws_update_service_entry,
        ws_delete_service_entry, ws_add_repair, ws_update_repair, ws_delete_repair,
        ws_add_tire, ws_delete_tire, ws_update_odometer,
    ]:
        websocket_api.async_register_command(hass, fn)


# ── HA actions (for automations / scripts) ────────────────────────────────────

def _register_services(hass: HomeAssistant) -> None:

    def _check(vehicle_id: str) -> None:
        if get_store(hass).get_vehicle(vehicle_id) is None:
            raise ServiceValidationError(f"Vehicle {vehicle_id} not found")

    async def handle_add_entry(call: ServiceCall) -> None:
        d = call.data
        _check(d["vehicle_id"])
        await get_store(hass).async_add_service_entry(
            vehicle_id=d["vehicle_id"], entry_date=d["entry_date"],
            odometer=d["odometer"], services=d["services"],
            notes=d["notes"], shop=d["shop"], cost=d["cost"],
        )

    async def handle_update_odometer(call: ServiceCall) -> None:
        _check(call.data["vehicle_id"])
        await get_store(hass).async_update_odometer(
            call.data["vehicle_id"], call.data["odometer"], call.data["allow_decrease"]
        )

    async def handle_add_repair(call: ServiceCall) -> None:
        _check(call.data["vehicle_id"])
        await get_store(hass).async_add_repair(call.data["vehicle_id"], _repair_from(call.data))

    async def handle_add_tire(call: ServiceCall) -> None:
        _check(call.data["vehicle_id"])
        await get_store(hass).async_add_tire(call.data["vehicle_id"], _tire_from(call.data))

    vid = {vol.Required("vehicle_id"): cv.string}
    hass.services.async_register(
        DOMAIN, HA_SERVICE_ADD_ENTRY, handle_add_entry,
        schema=vol.Schema({**vid, **_ENTRY_FIELDS}),
    )
    hass.services.async_register(
        DOMAIN, HA_SERVICE_UPDATE_ODOMETER, handle_update_odometer,
        schema=vol.Schema({
            **vid,
            vol.Required("odometer"): vol.Coerce(int),
            vol.Optional("allow_decrease", default=False): cv.boolean,
        }),
    )
    hass.services.async_register(
        DOMAIN, HA_SERVICE_ADD_REPAIR, handle_add_repair,
        schema=vol.Schema({**vid, **_REPAIR_FIELDS}),
    )
    hass.services.async_register(
        DOMAIN, HA_SERVICE_ADD_TIRE, handle_add_tire,
        schema=vol.Schema({**vid, **_TIRE_FIELDS}),
    )
