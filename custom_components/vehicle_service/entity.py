"""Base entity for Vehicle Service Manager."""
from __future__ import annotations

from typing import Any

from homeassistant.core import Event, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import EVENT_DATA_UPDATED
from .helpers import device_info
from .store import VehicleServiceStore


class VehicleEntity(Entity):
    """Reads from the shared store; refreshes on data changes and hourly."""

    _attr_has_entity_name = True
    _attr_should_poll = True  # hourly, so time-based intervals advance

    def __init__(self, store: VehicleServiceStore, vehicle_id: str) -> None:
        self._store = store
        self._vehicle_id = vehicle_id

    @property
    def vehicle(self) -> dict[str, Any] | None:
        return self._store.get_vehicle(self._vehicle_id)

    @property
    def device_info(self) -> DeviceInfo:
        return device_info(self.vehicle, self._vehicle_id)

    @property
    def available(self) -> bool:
        return self.vehicle is not None

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_update(event: Event) -> None:
            if event.data.get("vehicle_id") == self._vehicle_id:
                self.async_schedule_update_ha_state(force_refresh=True)

        self.async_on_remove(self.hass.bus.async_listen(EVENT_DATA_UPDATED, _on_update))

    async def async_update(self) -> None:
        vehicle = self.vehicle
        if vehicle is not None:
            self._refresh(vehicle)

    def _refresh(self, vehicle: dict[str, Any]) -> None:
        raise NotImplementedError
