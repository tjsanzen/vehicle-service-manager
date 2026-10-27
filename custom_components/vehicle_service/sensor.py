"""Sensor platform for Vehicle Service Manager."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN, SERVICE_ICONS, SERVICE_LABELS,
    TIRE_POSITIONS, TIRE_WEAR_32NDS_PER_MILE, TIRE_WARN_32NDS, TIRE_LEGAL_MIN_32NDS,
)
from .entity import VehicleEntity
from .helpers import service_progress
from .store import VehicleServiceStore, cost_summary, get_store

SCAN_INTERVAL = timedelta(hours=1)

STATUS_OPTIONS = ["ok", "watch", "soon", "due", "overdue"]


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

    currency = hass.config.currency or "USD"
    entities: list[SensorEntity] = [
        ServiceStatusSensor(store, vehicle_id, svc_id)
        for svc_id in vehicle.get("services", [])
    ]
    entities.append(OdometerSensor(store, vehicle_id))
    entities += [
        CostSensor(store, vehicle_id, "total", "Total cost", currency),
        CostSensor(store, vehicle_id, "ytd", "Cost this year", currency),
        CostSensor(store, vehicle_id, "last_12_months", "Cost last 12 months", currency),
        CostPerMileSensor(store, vehicle_id, currency),
    ]
    entities += [TireTreadSensor(store, vehicle_id, pos) for pos in TIRE_POSITIONS]

    async_add_entities(entities, update_before_add=True)


# ── Service status ────────────────────────────────────────────────────────────

class ServiceStatusSensor(VehicleEntity, SensorEntity):
    """ok / watch / soon / due / overdue for one service item."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_OPTIONS

    def __init__(self, store: VehicleServiceStore, vehicle_id: str, svc_id: str) -> None:
        super().__init__(store, vehicle_id)
        self._svc_id = svc_id
        self._attr_unique_id = f"{vehicle_id}_{svc_id}_status"
        self._attr_name = SERVICE_LABELS.get(svc_id, svc_id)
        self._attr_icon = SERVICE_ICONS.get(svc_id, "mdi:car-wrench")

    def _refresh(self, vehicle: dict[str, Any]) -> None:
        progress = service_progress(vehicle, self._svc_id)
        self._attr_native_value = progress["status"]
        self._attr_extra_state_attributes = {
            "vehicle_id": self._vehicle_id,
            "service_id": self._svc_id,
            **progress,
        }


# ── Odometer ──────────────────────────────────────────────────────────────────

class OdometerSensor(VehicleEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfLength.MILES
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:counter"
    _attr_name = "Odometer"

    def __init__(self, store: VehicleServiceStore, vehicle_id: str) -> None:
        super().__init__(store, vehicle_id)
        self._attr_unique_id = f"{vehicle_id}_odometer"

    def _refresh(self, vehicle: dict[str, Any]) -> None:
        self._attr_native_value = vehicle.get("odometer", 0)
        self._attr_extra_state_attributes = {"vehicle_id": self._vehicle_id}


# ── Costs ─────────────────────────────────────────────────────────────────────

class CostSensor(VehicleEntity, SensorEntity):
    """Spend across maintenance, repairs and tires."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash"

    def __init__(
        self, store: VehicleServiceStore, vehicle_id: str, key: str, name: str, currency: str
    ) -> None:
        super().__init__(store, vehicle_id)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{vehicle_id}_cost_{key}"
        self._attr_native_unit_of_measurement = currency
        if key == "total":
            self._attr_state_class = SensorStateClass.TOTAL

    def _refresh(self, vehicle: dict[str, Any]) -> None:
        summary = cost_summary(vehicle)
        self._attr_native_value = summary[self._key]
        attrs: dict[str, Any] = {
            "vehicle_id": self._vehicle_id,
            "maintenance": summary["by_category"]["maintenance"],
            "repairs": summary["by_category"]["repairs"],
            "tires": summary["by_category"]["tires"],
        }
        if self._key == "total":
            attrs["by_year"] = summary["by_year"]
        self._attr_extra_state_attributes = attrs


class CostPerMileSensor(VehicleEntity, SensorEntity):
    """Total spend divided by miles driven since the vehicle was added."""

    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash-marker"
    _attr_name = "Cost per mile"

    def __init__(self, store: VehicleServiceStore, vehicle_id: str, currency: str) -> None:
        super().__init__(store, vehicle_id)
        self._attr_unique_id = f"{vehicle_id}_cost_per_mile"
        self._attr_native_unit_of_measurement = f"{currency}/{UnitOfLength.MILES}"

    def _refresh(self, vehicle: dict[str, Any]) -> None:
        summary = cost_summary(vehicle)
        self._attr_native_value = summary["per_mile"]
        self._attr_extra_state_attributes = {
            "vehicle_id": self._vehicle_id,
            "miles_tracked": summary["miles_tracked"],
            "start_odometer": vehicle.get("startOdometer"),
        }


# ── Tires ─────────────────────────────────────────────────────────────────────

class TireTreadSensor(VehicleEntity, SensorEntity):
    """Projected tread depth (32nds of an inch) for one wheel."""

    _attr_native_unit_of_measurement = "/32 in"
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:tire"

    def __init__(self, store: VehicleServiceStore, vehicle_id: str, position: str) -> None:
        super().__init__(store, vehicle_id)
        self._position = position
        self._attr_unique_id = f"{vehicle_id}_tire_{position}"
        self._attr_name = f"Tire tread {TIRE_POSITIONS[position].lower()}"

    def _refresh(self, vehicle: dict[str, Any]) -> None:
        tires = [t for t in vehicle.get("tires", []) if float(t.get(self._position) or 0) > 0]
        if not tires:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        latest = tires[-1]
        measured = float(latest[self._position])
        measured_at = int(latest.get("odometer") or 0)
        driven = max(0, (vehicle.get("odometer") or 0) - measured_at)
        depth = round(max(0.0, measured - driven * TIRE_WEAR_32NDS_PER_MILE), 1)

        if depth <= TIRE_LEGAL_MIN_32NDS:
            status = "replace"
        elif depth <= TIRE_WARN_32NDS:
            status = "warning"
        else:
            status = "ok"

        self._attr_native_value = depth
        self._attr_extra_state_attributes = {
            "status": status,
            "measured_32nds": measured,
            "measured_date": latest.get("date"),
            "measured_odometer": measured_at,
            "miles_since_measured": driven,
            "tire_type": latest.get("type"),
            "brand": latest.get("brand"),
            "model": latest.get("model"),
            "size": latest.get("size"),
            "dot": latest.get("dot"),
        }
