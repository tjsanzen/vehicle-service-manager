"""Binary sensor platform for Vehicle Service Manager."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SERVICE_LABELS, STATUS_DUE_PCT
from .entity import VehicleEntity
from .helpers import service_progress
from .store import VehicleServiceStore, get_store

SCAN_INTERVAL = timedelta(hours=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = get_store(hass)
    await store.async_load()
    vehicle_id: str = hass.data[DOMAIN][entry.entry_id]["vehicle_id"]
    vehicle = store.get_vehicle(vehicle_id)
    if vehicle is None:
        return

    entities: list[BinarySensorEntity] = [
        ServiceDueSensor(store, vehicle_id, svc_id)
        for svc_id in vehicle.get("services", [])
    ]
    entities.append(AnyServiceDueSensor(store, vehicle_id))
    async_add_entities(entities, update_before_add=True)


class ServiceDueSensor(VehicleEntity, BinarySensorEntity):
    """On when a service item is due (≥ 90%) or overdue."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, store: VehicleServiceStore, vehicle_id: str, svc_id: str) -> None:
        super().__init__(store, vehicle_id)
        self._svc_id = svc_id
        self._attr_unique_id = f"{vehicle_id}_{svc_id}_due"
        self._attr_name = f"{SERVICE_LABELS.get(svc_id, svc_id)} due"

    def _refresh(self, vehicle: dict[str, Any]) -> None:
        p = service_progress(vehicle, self._svc_id)
        self._attr_is_on = p["raw_percentage"] >= STATUS_DUE_PCT
        self._attr_extra_state_attributes = {
            "service_id": self._svc_id,
            "percentage": p["percentage"],
            "status": p["status"],
            "miles_left": p["miles_left"],
            "months_left": p["months_left"],
            "next_due_odometer": p["next_due_odometer"],
            "next_due_date": p["next_due_date"],
        }


class AnyServiceDueSensor(VehicleEntity, BinarySensorEntity):
    """On when ANY service item is due or overdue."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:car-wrench"
    _attr_name = "Service due"

    def __init__(self, store: VehicleServiceStore, vehicle_id: str) -> None:
        super().__init__(store, vehicle_id)
        self._attr_unique_id = f"{vehicle_id}_any_due"

    def _refresh(self, vehicle: dict[str, Any]) -> None:
        due = [
            svc_id for svc_id in vehicle.get("services", [])
            if service_progress(vehicle, svc_id)["raw_percentage"] >= STATUS_DUE_PCT
        ]
        self._attr_is_on = bool(due)
        self._attr_extra_state_attributes = {
            "due_services": due,
            "due_labels": [SERVICE_LABELS.get(s, s) for s in due],
            "due_count": len(due),
        }
