# Changelog

## [2.0.0] - 2026-10-27

US edition. Not compatible with vehicles created by 1.x; delete and re-add them.

### Changed
- Miles instead of kilometers; English throughout
- New service list: oil change, tire rotation, multi-point inspection, wiper blades, engine/cabin air filter, brake fluid, coolant, transmission fluid, spark plugs, differential fluid, fuel filter, battery, registration, state inspection
- Setup asks for model year, in-service date, registration expiration and last state inspection
- Service items can be added or removed after setup (Configure)
- Tire tread in 32nds of an inch; positions LF/RF/LR/RR
- Items with no logged service are measured from new (odometer 0 / in-service date), so overdue items on a used car show up until you log them
- Odometer sensor ignores lower readings (glitches); km sources are converted

### Added
- Vehicle library (`vehicles.json`): per-vehicle maintenance schedules with generic fallback, first-interval overrides, inspect-only items and severe-conditions variants. Bundled: 2013–2014 Subaru Outback 2.5i CVT, 2017 Toyota RAV4 2.5L (both unverified)
- User library at `/config/vehicle_service/vehicles.json`
- Setup by VIN (NHTSA vPIC decoding), library pick, or manual entry (matched against the library)
- Configure: severe-schedule toggle and "reset intervals to the recommended schedule"
- Cost and shop on service entries, repairs and tires
- Sensors: total cost, cost this year, cost last 12 months, cost per mile
- Service sensor attributes: next due odometer/date, last service cost/shop
- `update_repair` WebSocket command; `update_odometer` action (replaces `update_km`)
- Tests (pytest-homeassistant-custom-component)

### Fixed
- Entities now refresh immediately after any change (repairs and tires didn't; binary sensors waited up to an hour)
- Event listeners and odometer tracking are cleaned up on reload
- Removed broken Lovelace auto-registration (referenced an undefined variable)

## [1.x] - 2026

Original metric, German-language release by [toxictody1337](https://github.com/toxictody1337/vehicle-service-manager), which this fork is based on.
