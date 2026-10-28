# Vehicle Service Manager (US)

Track maintenance, repairs, tires and what your cars cost in Home Assistant. US edition of [toxictody1337/vehicle-service-manager](https://github.com/toxictody1337/vehicle-service-manager): miles, US service items, and cost tracking.

## Features

- **15 service items**, each tracked by miles, months or both (whichever comes due first): oil change, tire rotation, multi-point inspection, wiper blades, engine and cabin air filters, brake fluid, coolant, transmission fluid, spark plugs, differential fluid, fuel filter, battery, registration and state inspection
- **Status** per item: `ok` → `watch` (50%) → `soon` (70%) → `due` (90%) → `overdue` (100%), plus next-due mileage and date
- **Costs** on every service, repair and tire entry, with the shop that did the work
- **Cost sensors**: total, this year, last 12 months and cost per mile, split into maintenance, repairs and tires
- **Live odometer** from any HA sensor (car integration, OBD dongle); km readings are converted
- **Tire tread** in 32nds of an inch, projected from the last measurement
- **Multiple vehicles**, one device each
- **Actions** for logging entries from automations, scripts or the dashboard

## Vehicle library

When you add a vehicle you can:

- **Look up by VIN.** Decoded with NHTSA's free vPIC service (make, model, year, engine, transmission, fuel).
- **Choose from the library** directly.
- **Enter it manually.** If the make, model and year match a library entry, it's offered to you.

A match pre-fills that vehicle's maintenance schedule. Anything the schedule doesn't list falls back to generic intervals, and everything stays editable. Schedules can include:

- **Miles and months.** Whichever comes due first wins.
- **A different first interval** (e.g. coolant at 100,000 mi, then every 50,000).
- **Inspect-only items.**
- **A severe-conditions variant**, offered as a toggle during setup.

Bundled schedules live in [`vehicles.json`](custom_components/vehicle_service/vehicles.json); the `_readme` block at the top documents every field. Currently included:

| Vehicle | Status |
|---|---|
| 2013–2014 Subaru Outback 2.5i CVT | Unverified – check against the 2013 booklet |
| 2017 Toyota RAV4 2.5L gas | Unverified – check against the 2017 guide |

**Add your own:** create `/config/vehicle_service/vehicles.json` with the same structure. It's read each time you add or configure a vehicle (no restart). Your schedules are checked first, and `generic` items you list replace the defaults. After editing a schedule, use **Configure → Reset intervals to the recommended schedule** on existing vehicles to pick up the changes.

Example:

```json
{
  "makes": {
    "honda": {
      "name": "Honda",
      "models": {
        "civic": {
          "name": "Civic",
          "schedules": [
            {
              "id": "honda-civic-2016-2021-2.0",
              "years": [2016, 2021],
              "engines": ["2.0"],
              "source": "2019 Civic owner's manual",
              "verified": true,
              "intervals": {
                "oil": { "miles": 7500, "months": 12 },
                "coolant": { "first_miles": 120000, "first_months": 120, "miles": 60000, "months": 60 }
              }
            }
          ]
        }
      }
    }
  }
}
```

## Installation (HACS)

1. HACS → three dots → **Custom repositories** → add this repo's URL as an **Integration**
2. Install **Vehicle Service Manager (US)** and restart Home Assistant
3. **Settings → Devices & services → Add integration → Vehicle Service Manager**

Setup identifies the vehicle (VIN, library or manual), then asks which items to track and their intervals. Check intervals against your owner's manual. Change any of it later with **Configure**.

> Upgrading from the original (metric) integration: vehicles created by it can't be migrated. Delete them before installing this version, then add them again.

## Dashboard card

The card is included with the integration and loads automatically; there's nothing to add under Resources. Edit a dashboard → **Add card** → **Vehicle Service**, then pick the vehicle.

It shows:
- The vehicle's name and photo
- Current mileage
- Up to three items due within 500 miles or 1 month, plus anything overdue
- **See all maintenance:** every tracked item with its progress, when it's due, and when it was last done
- **Log maintenance:** switch between **Maintenance** (scheduled items; resets their reminders) and **Repair** (one-off work like a control arm or alternator, with a category and description). Both take date, odometer, shop and cost, and count toward the cost sensors

Tapping an item opens the log form with that item already selected.

```yaml
type: custom:vehicle-service-card
device: 1a2b3c...            # chosen in the visual editor
image: /local/cars/outback.jpg
name: Outback                # optional, defaults to the device name
upcoming_miles: 500          # optional
upcoming_months: 1           # optional
max_items: 3                 # optional
```

For the photo, put a landscape image in `/config/www/cars/` and reference it as `/local/cars/<file>`.

## Entities

For a vehicle named "Toyota Camry":

| Entity | State |
|---|---|
| `sensor.toyota_camry_oil_change` (one per item) | `ok` / `watch` / `soon` / `due` / `overdue` |
| `binary_sensor.toyota_camry_oil_change_due` (one per item) | on at ≥ 90% |
| `binary_sensor.toyota_camry_service_due` | on if anything is due |
| `sensor.toyota_camry_odometer` | miles |
| `sensor.toyota_camry_total_cost` | lifetime spend |
| `sensor.toyota_camry_cost_this_year` | spend this calendar year |
| `sensor.toyota_camry_cost_last_12_months` | rolling 12-month spend |
| `sensor.toyota_camry_cost_per_mile` | spend since the car was added ÷ miles since |
| `sensor.toyota_camry_tire_tread_left_front` (×4) | projected tread, 32nds |

Service sensors carry `percentage`, `action` (`replace`/`inspect`), `note`, `miles_left`, `months_left`, `next_due_odometer`, `next_due_date`, `last_service_date`, `last_service_odometer`, `last_service_cost`, `last_service_shop`, `interval_miles` and `interval_months`.

Every sensor has a `vehicle_id` attribute, which the actions below need.

## Actions

```yaml
action: vehicle_service.add_service_entry
data:
  vehicle_id: "your-vehicle-id"
  entry_date: "2026-10-27"
  odometer: 61250
  services: [oil, tire_rotation]
  shop: "Valvoline – Plano"
  cost: 89.99
  notes: "0W-20 synthetic"
```

```yaml
action: vehicle_service.add_repair
data:
  vehicle_id: "your-vehicle-id"
  entry_date: "2026-10-27"
  odometer: 61250
  category: brakes_front   # see services.yaml for all categories
  description: "Pads and rotors"
  shop: "Firestone"
  cost: 412.50
```

```yaml
action: vehicle_service.add_tire
data:
  vehicle_id: "your-vehicle-id"
  entry_date: "2026-10-27"
  odometer: 61250
  tire_type: all_season
  axle: all
  size: "235/45R18"
  brand: "Michelin"
  model: "CrossClimate2"
  lf: 10
  rf: 10
  lr: 10
  rr: 10
  cost: 980
```

```yaml
action: vehicle_service.update_odometer
data:
  vehicle_id: "your-vehicle-id"
  odometer: 61500
```

Registration and state-inspection fees are logged with `add_service_entry` using `services: [registration]` or `[state_inspection]`, so they count toward costs and reset the reminder.

## Example automation

```yaml
alias: Car service reminder
triggers:
  - trigger: state
    entity_id: binary_sensor.toyota_camry_service_due
    to: "on"
actions:
  - action: notify.notify
    data:
      title: "Camry needs service"
      message: >
        Due: {{ state_attr('binary_sensor.toyota_camry_service_due', 'due_labels') | join(', ') }}
```

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest tests
```

## Disclaimer

Default intervals are general guidelines, not manufacturer recommendations.
