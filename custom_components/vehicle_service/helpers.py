"""Shared calculations for Vehicle Service Manager."""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, STATUS_DUE_PCT


def add_months(d: date, months: int) -> date:
    """Add (or subtract) whole months, clamping the day."""
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def months_between(start: date, end: date) -> float:
    return (end - start).days / 30.44


def parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def service_progress(vehicle: dict[str, Any], svc_id: str, today: date | None = None) -> dict[str, Any]:
    """Progress through one service interval — the worse of miles and time wins.

    Until an item has been logged once, it is measured from new (odometer 0 and
    the in-service date), using first_miles / first_months when the schedule has them.
    """
    today = today or date.today()
    last = vehicle.get("lastService", {}).get(svc_id) or {}
    intv = vehicle.get("intervals", {}).get(svc_id) or {}
    odometer = vehicle.get("odometer") or 0
    logged = bool(last)

    every_miles = intv.get("miles") if logged else intv.get("first_miles") or intv.get("miles")
    every_months = intv.get("months") if logged else intv.get("first_months") or intv.get("months")

    miles_pct = time_pct = None
    miles_left = months_left = next_due_odometer = next_due_date = None

    if every_miles:
        base = last.get("odometer") or 0
        driven = max(0, odometer - base)
        miles_pct = round(driven / every_miles * 100, 1)
        miles_left = every_miles - driven
        next_due_odometer = base + every_miles

    if every_months:
        base_date = parse_date(last.get("date")) or parse_date(vehicle.get("inServiceDate"))
        if base_date:
            elapsed = months_between(base_date, today)
            time_pct = round(elapsed / every_months * 100, 1)
            due = add_months(base_date, every_months)
            next_due_date = due.isoformat()
            months_left = round(months_between(today, due), 1)
        else:
            time_pct = 0.0
            months_left = float(every_months)

    candidates = [p for p in (miles_pct, time_pct) if p is not None]
    pct = max(candidates) if candidates else 0.0

    return {
        "percentage": min(pct, 100.0),
        "raw_percentage": pct,
        "status": status_from_pct(pct),
        "action": intv.get("action", "replace"),
        "note": intv.get("note"),
        "miles_left": miles_left,
        "months_left": months_left,
        "next_due_odometer": next_due_odometer,
        "next_due_date": next_due_date,
        "last_service_date": last.get("date"),
        "last_service_odometer": last.get("odometer"),
        "last_service_cost": last.get("cost"),
        "last_service_shop": last.get("shop"),
        "interval_miles": intv.get("miles"),
        "interval_months": intv.get("months"),
        "first_interval_miles": intv.get("first_miles"),
        "first_interval_months": intv.get("first_months"),
    }


def status_from_pct(pct: float) -> str:
    if pct >= 100:
        return "overdue"
    if pct >= STATUS_DUE_PCT:
        return "due"
    if pct >= 70:
        return "soon"
    if pct >= 50:
        return "watch"
    return "ok"


def device_info(vehicle: dict[str, Any] | None, vehicle_id: str) -> DeviceInfo:
    vehicle = vehicle or {}
    make, model, year = vehicle.get("make", ""), vehicle.get("model", ""), vehicle.get("year")
    name = " ".join(p for p in (make, model) if p)
    return DeviceInfo(
        identifiers={(DOMAIN, vehicle_id)},
        name=name or "Vehicle",
        manufacturer=make or None,
        model=" ".join(str(p) for p in (year, model) if p) or None,
        serial_number=vehicle.get("vin") or None,
    )
