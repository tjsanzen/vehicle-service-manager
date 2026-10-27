"""Config flow for Vehicle Service Manager (US edition).

Add vehicle:  menu (VIN / library / manual) → [pick schedule] → details → items → intervals
Options:      details → items → intervals
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN, CONFIG_VERSION,
    CONF_MAKE, CONF_MODEL, CONF_YEAR, CONF_IN_SERVICE_DATE, CONF_ODOMETER,
    CONF_PLATE, CONF_VIN, CONF_ODOMETER_ENTITY, CONF_SERVICES, CONF_INTERVALS,
    CONF_LAST_INSPECTION_DATE, CONF_LAST_INSPECTION_ODOMETER, CONF_REGISTRATION_EXPIRES,
    CONF_SCHEDULE, CONF_SEVERE, CONF_ENGINE, CONF_TRANSMISSION, CONF_FUEL,
    ALL_SERVICE_IDS, SERVICE_INTERVAL_TYPE,
    SERVICE_OIL, SERVICE_TIRE_ROTATION, SERVICE_WIPERS, SERVICE_AIR_FILTER,
    SERVICE_CABIN_FILTER, SERVICE_REGISTRATION,
)
from .library import Library, Schedule, VinDecodeError, async_decode_vin, async_load_library
from .store import get_store

DEFAULT_SELECTED = [
    SERVICE_OIL, SERVICE_TIRE_ROTATION, SERVICE_WIPERS,
    SERVICE_AIR_FILTER, SERVICE_CABIN_FILTER, SERVICE_REGISTRATION,
]
GENERIC = "generic"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

_MONTH_SELECTOR = selector.SelectSelector(selector.SelectSelectorConfig(
    options=[selector.SelectOptionDict(value=str(i + 1), label=m) for i, m in enumerate(MONTHS)],
    mode=selector.SelectSelectorMode.DROPDOWN,
))
_ODOMETER_SELECTOR = selector.NumberSelector(selector.NumberSelectorConfig(
    min=0, max=9_999_999, step=1, unit_of_measurement="mi", mode=selector.NumberSelectorMode.BOX,
))
_ODOMETER_ENTITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor")
)


def _year_selector(start_offset: int = 0, span: int = 40) -> selector.SelectSelector:
    top = date.today().year + start_offset
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=[str(y) for y in range(top, top - span, -1)],
        mode=selector.SelectSelectorMode.DROPDOWN,
    ))


def _schedule_selector(schedules: list[Schedule], include_generic: bool) -> selector.SelectSelector:
    options = [selector.SelectOptionDict(value=s.id, label=s.title) for s in schedules]
    if include_generic:
        options.append(selector.SelectOptionDict(value=GENERIC, label="None – use generic intervals"))
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=options, mode=selector.SelectSelectorMode.LIST,
    ))


def _month_year(user_input: dict[str, Any], prefix: str) -> str:
    """ISO date (1st of month) from <prefix>_month / <prefix>_year."""
    return date(int(user_input[f"{prefix}_year"]), int(user_input[f"{prefix}_month"]), 1).isoformat()


def _schedule_text(schedule: Schedule | None) -> str:
    if schedule is None:
        return "No matching schedule in the vehicle library, so generic intervals will be used."
    text = f"Using the {schedule.title} schedule from the vehicle library."
    if not schedule.verified:
        text += " Its intervals haven't been checked against the manufacturer's booklet yet."
    return text


def _vehicle_schema(data: dict[str, Any], include_initial: bool) -> vol.Schema:
    today = date.today()
    in_service = data.get(CONF_IN_SERVICE_DATE)
    try:
        d = date.fromisoformat(in_service) if in_service else None
    except ValueError:
        d = None
    year = str(data.get(CONF_YEAR) or today.year - 3)
    svc_month = str(d.month) if d else "1"
    svc_year = str(d.year) if d else year

    fields: dict = {
        vol.Required(CONF_MAKE, default=data.get(CONF_MAKE, "")): str,
        vol.Required(CONF_MODEL, default=data.get(CONF_MODEL, "")): str,
        vol.Required(CONF_YEAR, default=year): _year_selector(1),
        vol.Required("in_service_month", default=svc_month): _MONTH_SELECTOR,
        vol.Required("in_service_year", default=svc_year): _year_selector(1),
        vol.Required(CONF_ODOMETER, default=data.get(CONF_ODOMETER, 0)): _ODOMETER_SELECTOR,
        vol.Optional(CONF_PLATE, default=data.get(CONF_PLATE, "")): str,
        vol.Optional(CONF_VIN, default=data.get(CONF_VIN, "")): str,
        vol.Optional(
            CONF_ODOMETER_ENTITY,
            description={"suggested_value": data.get(CONF_ODOMETER_ENTITY) or None},
        ): _ODOMETER_ENTITY_SELECTOR,
    }
    if include_initial:
        fields.update({
            vol.Required("registration_known", default=False): bool,
            vol.Optional("registration_month", default=str(today.month)): _MONTH_SELECTOR,
            vol.Optional("registration_year", default=str(today.year)): _year_selector(2, 5),
            vol.Required("inspection_known", default=False): bool,
            vol.Optional("inspection_month", default=str(today.month)): _MONTH_SELECTOR,
            vol.Optional("inspection_year", default=str(today.year)): _year_selector(0, 5),
            vol.Optional("inspection_odometer", default=0): _ODOMETER_SELECTOR,
        })
    return vol.Schema(fields)


def _parse_vehicle(user_input: dict[str, Any], errors: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out[CONF_IN_SERVICE_DATE] = _month_year(user_input, "in_service")
    except (KeyError, ValueError):
        errors["in_service_month"] = "invalid_date"

    vin = (user_input.get(CONF_VIN) or "").strip().upper()
    if vin and len(vin) != 17:
        errors[CONF_VIN] = "vin_length"

    out.update({
        CONF_MAKE: user_input[CONF_MAKE].strip(),
        CONF_MODEL: user_input[CONF_MODEL].strip(),
        CONF_YEAR: int(user_input[CONF_YEAR]),
        CONF_ODOMETER: int(user_input.get(CONF_ODOMETER) or 0),
        CONF_PLATE: (user_input.get(CONF_PLATE) or "").strip().upper(),
        CONF_VIN: vin,
        CONF_ODOMETER_ENTITY: user_input.get(CONF_ODOMETER_ENTITY) or "",
    })
    return out


def _services_schema(selected: list[str], extra: dict | None = None) -> vol.Schema:
    fields: dict = {vol.Optional(sid, default=sid in selected): bool for sid in ALL_SERVICE_IDS}
    fields.update(extra or {})
    return vol.Schema(fields)


def _intervals_schema(selected: list[str], defaults: dict[str, dict]) -> vol.Schema:
    fields: dict = {}
    for sid in selected:
        itype = SERVICE_INTERVAL_TYPE.get(sid, "both")
        cur = defaults.get(sid) or {}
        if itype != "time":
            fields[vol.Optional(f"{sid}_miles", default=cur.get("miles", 0))] = vol.Coerce(int)
        if itype != "miles":
            fields[vol.Optional(f"{sid}_months", default=cur.get("months", 0))] = vol.Coerce(int)
    return vol.Schema(fields)


def _parse_intervals(
    selected: list[str], user_input: dict[str, Any], base: dict[str, dict]
) -> dict[str, dict]:
    """User-entered miles/months on top of the base (keeps first_*, action, note)."""
    intervals: dict[str, dict] = {}
    for sid in selected:
        itype = SERVICE_INTERVAL_TYPE.get(sid, "both")
        entry = {k: v for k, v in (base.get(sid) or {}).items() if k not in ("miles", "months")}
        if itype != "time" and int(user_input.get(f"{sid}_miles") or 0) > 0:
            entry["miles"] = int(user_input[f"{sid}_miles"])
        if itype != "miles" and int(user_input.get(f"{sid}_months") or 0) > 0:
            entry["months"] = int(user_input[f"{sid}_months"])
        intervals[sid] = entry
    return intervals


def _preselected(schedule: Schedule | None) -> list[str]:
    selected = set(DEFAULT_SELECTED)
    if schedule:
        selected |= set(schedule.intervals)
    return [sid for sid in ALL_SERVICE_IDS if sid in selected]


def _title(data: dict[str, Any]) -> str:
    return f"{data[CONF_YEAR]} {data[CONF_MAKE]} {data[CONF_MODEL]}"


class VehicleServiceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = CONFIG_VERSION

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._prefill: dict[str, Any] = {}
        self._library: Library | None = None
        self._schedule: Schedule | None = None
        self._schedule_chosen = False
        self._candidates: list[Schedule] = []

    async def _lib(self) -> Library:
        if self._library is None:
            self._library = await async_load_library(self.hass)
        return self._library

    # ── Step 1: how to identify the vehicle ───────────────────────────────────

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self._lib()
        return self.async_show_menu(step_id="user", menu_options=["vin", "library", "manual"])

    async def async_step_vin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            vin = user_input[CONF_VIN].strip().upper()
            if len(vin) != 17:
                errors[CONF_VIN] = "vin_length"
            else:
                await self.async_set_unique_id(vin)
                self._abort_if_unique_id_configured()
                try:
                    decoded = await async_decode_vin(self.hass, vin)
                except VinDecodeError as err:
                    errors["base"] = f"vin_{err.reason}"
                else:
                    self._prefill = {
                        CONF_MAKE: decoded["make"], CONF_MODEL: decoded["model"],
                        CONF_YEAR: decoded["year"], CONF_VIN: vin,
                        CONF_ENGINE: decoded["engine"], CONF_TRANSMISSION: decoded["transmission"],
                        CONF_FUEL: decoded["fuel"],
                    }
                    lib = await self._lib()
                    self._candidates = lib.find(
                        decoded["make"], decoded["model"], decoded["year"],
                        decoded["engine"], decoded["transmission"], decoded["fuel"],
                    )
                    return await self._after_identify()

        return self.async_show_form(
            step_id="vin",
            data_schema=vol.Schema({vol.Required(CONF_VIN): str}),
            errors=errors,
        )

    async def async_step_library(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        lib = await self._lib()
        if not lib.schedules:
            return await self.async_step_manual()
        errors: dict[str, str] = {}
        if user_input is not None:
            schedule = lib.get(user_input[CONF_SCHEDULE])
            year = int(user_input[CONF_YEAR])
            if schedule and not schedule.years[0] <= year <= schedule.years[1]:
                errors[CONF_YEAR] = "year_out_of_range"
            elif schedule:
                self._schedule, self._schedule_chosen = schedule, True
                self._prefill = {
                    CONF_MAKE: schedule.make, CONF_MODEL: schedule.model, CONF_YEAR: year,
                    CONF_ENGINE: (schedule.engines or [None])[0],
                    CONF_TRANSMISSION: (schedule.transmissions or [None])[0],
                    CONF_FUEL: (schedule.fuel or [None])[0],
                }
                return await self.async_step_details()

        return self.async_show_form(
            step_id="library",
            data_schema=vol.Schema({
                vol.Required(CONF_SCHEDULE): _schedule_selector(lib.schedules, include_generic=False),
                vol.Required(CONF_YEAR): _year_selector(1),
            }),
            errors=errors,
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._prefill = {}
        return await self.async_step_details()

    async def _after_identify(self) -> ConfigFlowResult:
        if len(self._candidates) == 1:
            self._schedule, self._schedule_chosen = self._candidates[0], True
            return await self.async_step_details()
        if len(self._candidates) > 1:
            return await self.async_step_pick_schedule()
        self._schedule, self._schedule_chosen = None, True
        return await self.async_step_details()

    async def async_step_pick_schedule(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            lib = await self._lib()
            self._schedule = lib.get(user_input[CONF_SCHEDULE])
            self._schedule_chosen = True
            if self._data:   # came here from the manual path
                return await self.async_step_services()
            return await self.async_step_details()

        p = {**self._prefill, **self._data}
        return self.async_show_form(
            step_id="pick_schedule",
            data_schema=vol.Schema({
                vol.Required(CONF_SCHEDULE): _schedule_selector(self._candidates, include_generic=True),
            }),
            description_placeholders={"vehicle": f"{p.get(CONF_YEAR, '')} {p.get(CONF_MAKE, '')} {p.get(CONF_MODEL, '')}".strip()},
        )

    # ── Step 2: vehicle details ───────────────────────────────────────────────

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            parsed = _parse_vehicle(user_input, errors)
            try:
                parsed[CONF_REGISTRATION_EXPIRES] = (
                    _month_year(user_input, "registration")
                    if user_input.get("registration_known") else None
                )
            except (KeyError, ValueError):
                errors["registration_month"] = "invalid_date"
            try:
                if user_input.get("inspection_known"):
                    parsed[CONF_LAST_INSPECTION_DATE] = _month_year(user_input, "inspection")
                    parsed[CONF_LAST_INSPECTION_ODOMETER] = int(user_input.get("inspection_odometer") or 0)
                else:
                    parsed[CONF_LAST_INSPECTION_DATE] = None
                    parsed[CONF_LAST_INSPECTION_ODOMETER] = 0
            except (KeyError, ValueError):
                errors["inspection_month"] = "invalid_date"

            if parsed.get(CONF_VIN) and not self.unique_id:
                await self.async_set_unique_id(parsed[CONF_VIN])
                self._abort_if_unique_id_configured()

            if not errors:
                self._data.update({
                    CONF_ENGINE: self._prefill.get(CONF_ENGINE),
                    CONF_TRANSMISSION: self._prefill.get(CONF_TRANSMISSION),
                    CONF_FUEL: self._prefill.get(CONF_FUEL),
                    **parsed,
                })
                if not self._schedule_chosen:
                    # Manual entry: still look for a schedule by make/model/year
                    lib = await self._lib()
                    self._candidates = lib.find(parsed[CONF_MAKE], parsed[CONF_MODEL], parsed[CONF_YEAR])
                    if self._candidates:
                        return await self.async_step_pick_schedule()
                    self._schedule_chosen = True
                return await self.async_step_services()

        return self.async_show_form(
            step_id="details",
            data_schema=self.add_suggested_values_to_schema(
                _vehicle_schema(self._prefill, include_initial=True), user_input or {}
            ),
            errors=errors,
            description_placeholders={
                "schedule": _schedule_text(self._schedule) if self._schedule_chosen
                else "Enter the vehicle; the library is checked for a matching schedule next.",
            },
        )

    # ── Step 3: items ─────────────────────────────────────────────────────────

    async def async_step_services(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        has_severe = bool(self._schedule and self._schedule.severe)
        if user_input is not None:
            selected = [sid for sid in ALL_SERVICE_IDS if user_input.get(sid)]
            if selected:
                self._data[CONF_SERVICES] = selected
                self._data[CONF_SEVERE] = bool(user_input.get(CONF_SEVERE)) and has_severe
                return await self.async_step_intervals()
            errors["base"] = "no_service_selected"

        extra = {vol.Optional(CONF_SEVERE, default=False): bool} if has_severe else None
        return self.async_show_form(
            step_id="services",
            data_schema=_services_schema(_preselected(self._schedule), extra),
            errors=errors,
            description_placeholders={"schedule": _schedule_text(self._schedule)},
        )

    # ── Step 4: intervals ─────────────────────────────────────────────────────

    async def async_step_intervals(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        lib = await self._lib()
        selected: list[str] = self._data[CONF_SERVICES]
        base = lib.intervals_for(self._schedule, self._data.get(CONF_SEVERE, False))
        if user_input is not None:
            self._data[CONF_INTERVALS] = _parse_intervals(selected, user_input, base)
            self._data[CONF_SCHEDULE] = self._schedule.id if self._schedule else None
            return self.async_create_entry(
                title=_title(self._data),
                data={"vehicle_id": str(uuid.uuid4()), **self._data},
            )

        return self.async_show_form(
            step_id="intervals",
            data_schema=_intervals_schema(selected, base),
            description_placeholders={"schedule": _schedule_text(self._schedule)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return VehicleServiceOptionsFlow()


class VehicleServiceOptionsFlow(config_entries.OptionsFlow):
    """Edit vehicle data, tracked items and intervals."""

    def __init__(self) -> None:
        self._new: dict[str, Any] = {}
        self._reset = False

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        store = get_store(self.hass)
        vehicle = store.get_vehicle(self.config_entry.data["vehicle_id"]) or {}
        # Show the live odometer, not the one entered at setup
        data = {**self.config_entry.data, CONF_ODOMETER: vehicle.get("odometer", 0)}
        errors: dict[str, str] = {}
        if user_input is not None:
            parsed = _parse_vehicle(user_input, errors)
            if not errors:
                odometer = parsed.pop(CONF_ODOMETER)
                if odometer != vehicle.get("odometer"):
                    await store.async_update_odometer(
                        self.config_entry.data["vehicle_id"], odometer, allow_decrease=True
                    )
                self._new.update(parsed)
                return await self.async_step_services()

        return self.async_show_form(
            step_id="init",
            data_schema=_vehicle_schema(data, include_initial=False),
            errors=errors,
        )

    async def async_step_services(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        lib = await async_load_library(self.hass)
        schedule = lib.get(self.config_entry.data.get(CONF_SCHEDULE))
        has_severe = bool(schedule and schedule.severe)
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = [sid for sid in ALL_SERVICE_IDS if user_input.get(sid)]
            if selected:
                self._new[CONF_SERVICES] = selected
                self._new[CONF_SEVERE] = bool(user_input.get(CONF_SEVERE)) and has_severe
                self._reset = bool(user_input.get("reset_intervals")) or (
                    self._new[CONF_SEVERE] != self.config_entry.data.get(CONF_SEVERE, False)
                )
                return await self.async_step_intervals()
            errors["base"] = "no_service_selected"

        extra: dict = {}
        if has_severe:
            extra[vol.Optional(CONF_SEVERE, default=self.config_entry.data.get(CONF_SEVERE, False))] = bool
        extra[vol.Optional("reset_intervals", default=False)] = bool
        return self.async_show_form(
            step_id="services",
            data_schema=_services_schema(self.config_entry.data.get(CONF_SERVICES, []), extra),
            errors=errors,
            description_placeholders={"schedule": _schedule_text(schedule)},
        )

    async def async_step_intervals(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        lib = await async_load_library(self.hass)
        schedule = lib.get(self.config_entry.data.get(CONF_SCHEDULE))
        selected: list[str] = self._new[CONF_SERVICES]
        recommended = lib.intervals_for(schedule, self._new.get(CONF_SEVERE, False))
        current = self.config_entry.data.get(CONF_INTERVALS, {})
        base = recommended if self._reset else {
            sid: current.get(sid) or recommended.get(sid, {}) for sid in ALL_SERVICE_IDS
        }

        if user_input is not None:
            data = {
                **self.config_entry.data,
                **self._new,
                CONF_INTERVALS: _parse_intervals(selected, user_input, base),
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=data, title=_title(data),
            )
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="intervals",
            data_schema=_intervals_schema(selected, base),
            description_placeholders={"schedule": _schedule_text(schedule)},
        )
