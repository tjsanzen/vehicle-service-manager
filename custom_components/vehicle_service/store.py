"""Persistent storage for Vehicle Service Manager.

A single shared store instance per HA instance is kept in hass.data[DOMAIN]["_store"].
Every config entry (= every vehicle) reads from and writes to this shared store so
there is exactly one in-memory dict and one .storage file.

Every mutation fires EVENT_DATA_UPDATED with the vehicle_id so entities refresh.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, EVENT_DATA_UPDATED, STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


def get_store(hass: HomeAssistant) -> "VehicleServiceStore":
    """Return (or create) the single shared store for this HA instance."""
    if "_store" not in hass.data.setdefault(DOMAIN, {}):
        hass.data[DOMAIN]["_store"] = VehicleServiceStore(hass)
    return hass.data[DOMAIN]["_store"]


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


class VehicleServiceStore:
    """Single shared store — holds ALL vehicles in one .storage file."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {"vehicles": {}}
        self._loaded = False

    async def async_load(self) -> None:
        if self._loaded:
            return
        stored = await self._store.async_load()
        self._data = stored or {"vehicles": {}}
        self._loaded = True
        _LOGGER.debug(
            "Vehicle service store loaded – %d vehicle(s)",
            len(self._data.get("vehicles", {})),
        )

    async def _async_commit(self, vehicle_id: str) -> None:
        await self._store.async_save(self._data)
        self._hass.bus.async_fire(EVENT_DATA_UPDATED, {"vehicle_id": vehicle_id})

    def _require(self, vehicle_id: str) -> dict[str, Any]:
        vehicle = self.get_vehicle(vehicle_id)
        if vehicle is None:
            raise KeyError(f"Vehicle {vehicle_id} not found")
        return vehicle

    # ── Vehicle CRUD ──────────────────────────────────────────────────────────

    def get_vehicles(self) -> dict[str, Any]:
        return self._data.get("vehicles", {})

    def get_vehicle(self, vehicle_id: str) -> dict[str, Any] | None:
        return self._data.get("vehicles", {}).get(vehicle_id)

    async def async_add_vehicle(self, vehicle_id: str, vehicle_data: dict[str, Any]) -> None:
        self._data.setdefault("vehicles", {})[vehicle_id] = vehicle_data
        await self._async_commit(vehicle_id)

    async def async_update_vehicle(self, vehicle_id: str, updates: dict[str, Any]) -> None:
        self._require(vehicle_id).update(updates)
        await self._async_commit(vehicle_id)

    async def async_remove_vehicle(self, vehicle_id: str) -> None:
        self._data.get("vehicles", {}).pop(vehicle_id, None)
        await self._store.async_save(self._data)

    # ── Odometer ──────────────────────────────────────────────────────────────

    async def async_update_odometer(
        self, vehicle_id: str, odometer: int, allow_decrease: bool = False
    ) -> bool:
        """Set the odometer. Lower readings are ignored unless allow_decrease."""
        vehicle = self.get_vehicle(vehicle_id)
        if vehicle is None:
            return False
        current = vehicle.get("odometer") or 0
        if odometer == current or (odometer < current and not allow_decrease):
            return False
        vehicle["odometer"] = odometer
        await self._async_commit(vehicle_id)
        return True

    def _bump_odometer(self, vehicle: dict[str, Any], odometer: int) -> None:
        if odometer > (vehicle.get("odometer") or 0):
            vehicle["odometer"] = odometer

    # ── Service history ───────────────────────────────────────────────────────

    def get_history(self, vehicle_id: str) -> list[dict[str, Any]]:
        vehicle = self.get_vehicle(vehicle_id)
        return vehicle.get("history", []) if vehicle else []

    @staticmethod
    def _service_entry(
        entry_date: str, odometer: int, services: list[str], notes: str = "",
        shop: str = "", cost: float = 0, auto: bool = False,
    ) -> dict[str, Any]:
        return {
            "date": entry_date,
            "odometer": int(odometer or 0),
            "services": list(services),
            "notes": notes or "",
            "shop": shop or "",
            "cost": _money(cost),
            "auto": auto,
        }

    async def async_add_service_entry(
        self,
        vehicle_id: str,
        entry_date: str,
        odometer: int,
        services: list[str],
        notes: str = "",
        shop: str = "",
        cost: float = 0,
        auto: bool = False,
    ) -> dict[str, Any]:
        vehicle = self._require(vehicle_id)
        entry = self._service_entry(entry_date, odometer, services, notes, shop, cost, auto)
        vehicle.setdefault("history", []).append(entry)
        self._recalc_last_service(vehicle)
        self._bump_odometer(vehicle, entry["odometer"])
        await self._async_commit(vehicle_id)
        return entry

    async def async_update_service_entry(
        self, vehicle_id: str, entry_index: int, entry_date: str, odometer: int,
        services: list[str], notes: str = "", shop: str = "", cost: float = 0,
    ) -> None:
        vehicle = self._require(vehicle_id)
        history = vehicle.get("history", [])
        if not 0 <= entry_index < len(history):
            raise IndexError("Entry index out of range")
        history[entry_index] = self._service_entry(
            entry_date, odometer, services, notes, shop, cost,
            history[entry_index].get("auto", False),
        )
        self._recalc_last_service(vehicle)
        self._bump_odometer(vehicle, int(odometer or 0))
        await self._async_commit(vehicle_id)

    async def async_delete_service_entry(self, vehicle_id: str, entry_index: int) -> None:
        vehicle = self._require(vehicle_id)
        history = vehicle.get("history", [])
        if 0 <= entry_index < len(history):
            history.pop(entry_index)
        self._recalc_last_service(vehicle)
        await self._async_commit(vehicle_id)

    @staticmethod
    def _recalc_last_service(vehicle: dict[str, Any]) -> None:
        """Most recent entry per service wins (by date, then odometer)."""
        last_service: dict[str, Any] = {}
        for entry in vehicle.get("history", []):
            key = (entry.get("date") or "", entry.get("odometer") or 0)
            for svc_id in entry.get("services", []):
                current = last_service.get(svc_id)
                cur_key = (current.get("date") or "", current.get("odometer") or 0) if current else None
                if current is None or key >= cur_key:
                    last_service[svc_id] = {
                        "odometer": entry.get("odometer"),
                        "date": entry.get("date"),
                        "cost": entry.get("cost", 0),
                        "shop": entry.get("shop", ""),
                    }
        vehicle["lastService"] = last_service

    # ── Repairs ───────────────────────────────────────────────────────────────

    def get_repairs(self, vehicle_id: str) -> list[dict[str, Any]]:
        vehicle = self.get_vehicle(vehicle_id)
        return vehicle.get("repairs", []) if vehicle else []

    async def async_add_repair(self, vehicle_id: str, repair: dict[str, Any]) -> None:
        vehicle = self._require(vehicle_id)
        repair = {**repair, "cost": _money(repair.get("cost"))}
        vehicle.setdefault("repairs", []).append(repair)
        self._bump_odometer(vehicle, int(repair.get("odometer") or 0))
        await self._async_commit(vehicle_id)

    async def async_update_repair(
        self, vehicle_id: str, repair_index: int, repair: dict[str, Any]
    ) -> None:
        vehicle = self._require(vehicle_id)
        repairs = vehicle.get("repairs", [])
        if not 0 <= repair_index < len(repairs):
            raise IndexError("Repair index out of range")
        repairs[repair_index] = {**repair, "cost": _money(repair.get("cost"))}
        await self._async_commit(vehicle_id)

    async def async_delete_repair(self, vehicle_id: str, repair_index: int) -> None:
        vehicle = self._require(vehicle_id)
        repairs = vehicle.get("repairs", [])
        if 0 <= repair_index < len(repairs):
            repairs.pop(repair_index)
        await self._async_commit(vehicle_id)

    # ── Tires ─────────────────────────────────────────────────────────────────

    def get_tires(self, vehicle_id: str) -> list[dict[str, Any]]:
        vehicle = self.get_vehicle(vehicle_id)
        return vehicle.get("tires", []) if vehicle else []

    async def async_add_tire(self, vehicle_id: str, tire: dict[str, Any]) -> None:
        vehicle = self._require(vehicle_id)
        tire = {**tire, "cost": _money(tire.get("cost"))}
        vehicle.setdefault("tires", []).append(tire)
        self._bump_odometer(vehicle, int(tire.get("odometer") or 0))
        await self._async_commit(vehicle_id)

    async def async_delete_tire(self, vehicle_id: str, tire_index: int) -> None:
        vehicle = self._require(vehicle_id)
        tires = vehicle.get("tires", [])
        if 0 <= tire_index < len(tires):
            tires.pop(tire_index)
        await self._async_commit(vehicle_id)


# ── Cost summary ──────────────────────────────────────────────────────────────

def cost_summary(vehicle: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Totals across service history, repairs and tires."""
    today = today or date.today()
    year = str(today.year)
    last_12_start = date(today.year - 1, today.month, min(today.day, 28)).isoformat()

    start_odo = vehicle.get("startOdometer") or 0
    records: list[tuple[str, dict[str, Any]]] = (
        [("maintenance", e) for e in vehicle.get("history", [])]
        + [("repairs", r) for r in vehicle.get("repairs", [])]
        + [("tires", t) for t in vehicle.get("tires", [])]
    )

    by_category = {"maintenance": 0.0, "repairs": 0.0, "tires": 0.0}
    by_year: dict[str, float] = {}
    total = ytd = last_12 = since_start = 0.0
    for cat, rec in records:
        cost = _money(rec.get("cost"))
        if not cost:
            continue
        d = rec.get("date") or ""
        total += cost
        # Only spend logged at/after the starting odometer counts toward cost per mile
        if (rec.get("odometer") or 0) >= start_odo:
            since_start += cost
        by_category[cat] += cost
        y = d[:4] or "unknown"
        by_year[y] = by_year.get(y, 0.0) + cost
        if d.startswith(year):
            ytd += cost
        if d and d >= last_12_start:
            last_12 += cost

    miles = (vehicle.get("odometer") or 0) - start_odo
    per_mile = round(since_start / miles, 3) if miles > 0 and since_start else None

    return {
        "total": round(total, 2),
        "ytd": round(ytd, 2),
        "last_12_months": round(last_12, 2),
        "per_mile": per_mile,
        "miles_tracked": max(miles, 0),
        "by_category": {k: round(v, 2) for k, v in by_category.items()},
        "by_year": {k: round(v, 2) for k, v in sorted(by_year.items())},
    }
