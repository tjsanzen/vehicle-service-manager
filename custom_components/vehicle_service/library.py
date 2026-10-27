"""Vehicle maintenance library (vehicles.json) and VIN decoding."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import ALL_SERVICE_IDS

_LOGGER = logging.getLogger(__name__)

BUNDLED_FILE = Path(__file__).parent / "vehicles.json"
USER_FILE = "vehicle_service/vehicles.json"   # relative to /config
VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"

INTERVAL_KEYS = ("miles", "months", "first_miles", "first_months", "action", "note")


def norm_key(value: Any) -> str:
    """'Land Rover' -> 'landrover', 'RAV4' -> 'rav4'."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def clean_interval(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in INTERVAL_KEYS:
        val = raw.get(key)
        if val in (None, "", 0):
            continue
        if key in ("miles", "months", "first_miles", "first_months"):
            try:
                val = int(val)
            except (TypeError, ValueError):
                continue
        out[key] = val
    return out


@dataclass
class Schedule:
    id: str
    make: str
    model: str
    years: tuple[int, int]
    engines: list[str] = field(default_factory=list)
    transmissions: list[str] = field(default_factory=list)
    fuel: list[str] = field(default_factory=list)
    label: str = ""
    source: str = ""
    verified: bool = False
    intervals: dict[str, dict] = field(default_factory=dict)
    severe: dict[str, dict] = field(default_factory=dict)

    @property
    def title(self) -> str:
        y1, y2 = self.years
        years = str(y1) if y1 == y2 else f"{y1}–{y2}"
        parts = [f"{self.make} {self.model} {years}"]
        if self.label:
            parts.append(self.label)
        if not self.verified:
            parts.append("unverified")
        return " · ".join(parts)

    def matches(
        self, year: int | None, engine: str | None = None,
        transmission: str | None = None, fuel: str | None = None,
    ) -> bool:
        if year is not None and not self.years[0] <= year <= self.years[1]:
            return False
        # Unknown details from the VIN don't rule a schedule out
        if engine and self.engines and engine not in self.engines:
            return False
        if transmission and self.transmissions and transmission not in self.transmissions:
            return False
        if fuel and self.fuel and fuel not in self.fuel:
            return False
        return True


@dataclass
class Library:
    generic: dict[str, dict]
    schedules: list[Schedule]
    # {make_key: {"name": str, "models": {model_key: name}}}
    names: dict[str, dict]

    def get(self, schedule_id: str | None) -> Schedule | None:
        return next((s for s in self.schedules if s.id == schedule_id), None)

    def find(
        self, make: str, model: str, year: int | None, engine: str | None = None,
        transmission: str | None = None, fuel: str | None = None,
    ) -> list[Schedule]:
        mk, md = norm_key(make), norm_key(model)
        return [
            s for s in self.schedules
            if norm_key(s.make) == mk and _model_matches(norm_key(s.model), md)
            and s.matches(year, engine, transmission, fuel)
        ]

    def intervals_for(self, schedule: Schedule | None, severe: bool = False) -> dict[str, dict]:
        """Generic fallback, overlaid with the schedule, overlaid with severe."""
        result = {sid: dict(self.generic.get(sid, {})) for sid in ALL_SERVICE_IDS}
        if schedule:
            result.update({k: dict(v) for k, v in schedule.intervals.items()})
            if severe:
                for sid, override in schedule.severe.items():
                    result[sid] = {**result.get(sid, {}), **override}
        return result


def _model_matches(schedule_model: str, decoded_model: str) -> bool:
    # vPIC sometimes adds words ("Outback Wagon"); accept a prefix match
    return decoded_model == schedule_model or decoded_model.startswith(schedule_model)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as err:
        _LOGGER.error("Could not read vehicle library %s: %s", path, err)
        return None


def _parse(data: dict[str, Any], origin: str) -> tuple[dict[str, dict], list[Schedule], dict[str, dict]]:
    generic = {
        sid: clean_interval(v) for sid, v in (data.get("generic") or {}).items()
        if sid in ALL_SERVICE_IDS
    }
    schedules: list[Schedule] = []
    names: dict[str, dict] = {}
    for make_key, make in (data.get("makes") or {}).items():
        make_name = make.get("name") or make_key.title()
        names.setdefault(norm_key(make_key), {"name": make_name, "models": {}})
        for model_key, model in (make.get("models") or {}).items():
            model_name = model.get("name") or model_key.upper()
            names[norm_key(make_key)]["models"][norm_key(model_key)] = model_name
            for raw in model.get("schedules") or []:
                try:
                    y1, y2 = (int(y) for y in raw["years"])
                    sched = Schedule(
                        id=str(raw["id"]),
                        make=make_name, model=model_name, years=(y1, y2),
                        engines=[str(e) for e in raw.get("engines") or []],
                        transmissions=[str(t).lower() for t in raw.get("transmissions") or []],
                        fuel=[str(f).lower() for f in raw.get("fuel") or []],
                        label=raw.get("label", ""), source=raw.get("source", ""),
                        verified=bool(raw.get("verified", False)),
                        intervals={
                            sid: clean_interval(v) for sid, v in (raw.get("intervals") or {}).items()
                            if sid in ALL_SERVICE_IDS
                        },
                        severe={
                            sid: clean_interval(v) for sid, v in (raw.get("severe") or {}).items()
                            if sid in ALL_SERVICE_IDS
                        },
                    )
                except (KeyError, TypeError, ValueError) as err:
                    _LOGGER.error(
                        "Skipping invalid schedule under %s/%s in %s: %s",
                        make_key, model_key, origin, err,
                    )
                    continue
                unknown = set(raw.get("intervals") or {}) - set(ALL_SERVICE_IDS)
                if unknown:
                    _LOGGER.warning("Schedule %s: unknown service ids ignored: %s", sched.id, unknown)
                schedules.append(sched)
    return generic, schedules, names


def load_library(config_dir: str) -> Library:
    """Load bundled + user library (blocking; run in executor)."""
    bundled = _read_json(BUNDLED_FILE) or {}
    generic, schedules, names = _parse(bundled, str(BUNDLED_FILE))

    user_path = Path(config_dir) / USER_FILE
    user = _read_json(user_path)
    if user:
        u_generic, u_schedules, u_names = _parse(user, str(user_path))
        generic.update(u_generic)
        user_ids = {s.id for s in u_schedules}
        # User schedules first so they win; same id replaces the bundled one
        schedules = u_schedules + [s for s in schedules if s.id not in user_ids]
        for mk, info in u_names.items():
            names.setdefault(mk, {"name": info["name"], "models": {}})["models"].update(info["models"])
    return Library(generic=generic, schedules=schedules, names=names)


async def async_load_library(hass: HomeAssistant) -> Library:
    return await hass.async_add_executor_job(load_library, hass.config.config_dir)


# ── VIN decoding (NHTSA vPIC, free, no key) ───────────────────────────────────

class VinDecodeError(Exception):
    """Lookup failed (network) or VIN not recognized."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason   # "lookup_failed" | "not_found"


def _transmission(style: str) -> str | None:
    s = style.lower()
    if "continuously" in s or "cvt" in s:
        return "cvt"
    if "manual" in s:
        return "manual"
    if "automatic" in s or "dct" in s or "dual-clutch" in s:
        return "automatic"
    return None


def _fuel(primary: str, electrification: str) -> str | None:
    e = electrification.lower()
    if "phev" in e or "plug-in" in e:
        return "plug_in_hybrid"
    if "bev" in e or "battery electric" in e:
        return "electric"
    if "hev" in e:
        return "hybrid"
    p = primary.lower()
    if "diesel" in p:
        return "diesel"
    if "electric" in p:
        return "electric"
    if "gasoline" in p:
        return "gasoline"
    return None


def parse_vpic(result: dict[str, Any]) -> dict[str, Any]:
    """Pick the fields we care about out of a vPIC DecodeVinValues result."""
    def s(key: str) -> str:
        return str(result.get(key) or "").strip()

    try:
        year: int | None = int(s("ModelYear"))
    except ValueError:
        year = None
    try:
        engine: str | None = f"{float(s('DisplacementL')):.1f}"
    except ValueError:
        engine = None

    return {
        "make": s("Make").title(),
        "model": s("Model"),
        "year": year,
        "trim": s("Trim") or s("Series"),
        "engine": engine,
        "transmission": _transmission(s("TransmissionStyle")),
        "fuel": _fuel(s("FuelTypePrimary"), s("ElectrificationLevel")),
    }


async def async_decode_vin(hass: HomeAssistant, vin: str) -> dict[str, Any]:
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(15):
            resp = await session.get(VPIC_URL.format(vin=vin))
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        _LOGGER.warning("VIN lookup failed: %s", err)
        raise VinDecodeError("lookup_failed") from err

    results = data.get("Results") or []
    decoded = parse_vpic(results[0]) if results else {}
    if not decoded.get("make") or not decoded.get("model") or not decoded.get("year"):
        raise VinDecodeError("not_found")
    return decoded
