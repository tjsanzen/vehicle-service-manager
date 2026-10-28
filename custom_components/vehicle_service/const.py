"""Constants for Vehicle Service Manager (US edition)."""

DOMAIN = "vehicle_service"
PLATFORMS = ["sensor", "binary_sensor"]

# Storage
STORAGE_VERSION = 1
STORAGE_KEY = "vehicle_service"

# Config entry version. Entries created by the original (German/metric)
# integration are version 1 and are not migrated.
CONFIG_VERSION = 2

# Config flow keys
CONF_MAKE = "make"
CONF_MODEL = "model"
CONF_YEAR = "year"                       # model year
CONF_IN_SERVICE_DATE = "in_service_date"  # ISO date, start point for time intervals
CONF_ODOMETER = "odometer"
CONF_PLATE = "plate"
CONF_VIN = "vin"
CONF_ODOMETER_ENTITY = "odometer_entity"  # optional live odometer sensor
CONF_SERVICES = "services"               # list of selected service IDs
CONF_INTERVALS = "intervals"             # {service_id: {"miles"?: int, "months"?: int}}
CONF_LAST_INSPECTION_DATE = "last_inspection_date"
CONF_LAST_INSPECTION_ODOMETER = "last_inspection_odometer"
CONF_REGISTRATION_EXPIRES = "registration_expires"
CONF_SCHEDULE = "schedule_id"             # vehicles.json schedule id, or None for generic
CONF_SEVERE = "severe_schedule"
CONF_ENGINE = "engine"                   # displacement in liters, e.g. "2.5"
CONF_TRANSMISSION = "transmission"       # automatic / cvt / manual
CONF_FUEL = "fuel"

# Units
KM_PER_MILE = 1.609344

# Service IDs
SERVICE_OIL = "oil"
SERVICE_TIRE_ROTATION = "tire_rotation"
SERVICE_INSPECTION = "inspection"
SERVICE_WIPERS = "wipers"
SERVICE_AIR_FILTER = "air_filter"
SERVICE_CABIN_FILTER = "cabin_filter"
SERVICE_BRAKE_FLUID = "brake_fluid"
SERVICE_COOLANT = "coolant"
SERVICE_TRANSMISSION = "transmission"
SERVICE_SPARK_PLUGS = "spark_plugs"
SERVICE_DIFFERENTIAL = "differential"
SERVICE_FUEL_FILTER = "fuel_filter"
SERVICE_BATTERY = "battery"
SERVICE_REGISTRATION = "registration"
SERVICE_STATE_INSPECTION = "state_inspection"

ALL_SERVICE_IDS = [
    SERVICE_OIL,
    SERVICE_TIRE_ROTATION,
    SERVICE_INSPECTION,
    SERVICE_WIPERS,
    SERVICE_AIR_FILTER,
    SERVICE_CABIN_FILTER,
    SERVICE_BRAKE_FLUID,
    SERVICE_COOLANT,
    SERVICE_TRANSMISSION,
    SERVICE_SPARK_PLUGS,
    SERVICE_DIFFERENTIAL,
    SERVICE_FUEL_FILTER,
    SERVICE_BATTERY,
    SERVICE_REGISTRATION,
    SERVICE_STATE_INSPECTION,
]

SERVICE_LABELS = {
    SERVICE_OIL: "Oil change",
    SERVICE_TIRE_ROTATION: "Tire rotation",
    SERVICE_INSPECTION: "Multi-point inspection",
    SERVICE_WIPERS: "Wiper blades",
    SERVICE_AIR_FILTER: "Engine air filter",
    SERVICE_CABIN_FILTER: "Cabin air filter",
    SERVICE_BRAKE_FLUID: "Brake fluid",
    SERVICE_COOLANT: "Coolant",
    SERVICE_TRANSMISSION: "Transmission fluid",
    SERVICE_SPARK_PLUGS: "Spark plugs",
    SERVICE_DIFFERENTIAL: "Differential fluid",
    SERVICE_FUEL_FILTER: "Fuel filter",
    SERVICE_BATTERY: "Battery",
    SERVICE_REGISTRATION: "Registration",
    SERVICE_STATE_INSPECTION: "State inspection",
}

SERVICE_ICONS = {
    SERVICE_OIL: "mdi:oil",
    SERVICE_TIRE_ROTATION: "mdi:tire",
    SERVICE_INSPECTION: "mdi:clipboard-check-outline",
    SERVICE_WIPERS: "mdi:wiper",
    SERVICE_AIR_FILTER: "mdi:air-filter",
    SERVICE_CABIN_FILTER: "mdi:air-filter",
    SERVICE_BRAKE_FLUID: "mdi:car-brake-fluid-level",
    SERVICE_COOLANT: "mdi:coolant-temperature",
    SERVICE_TRANSMISSION: "mdi:car-shift-pattern",
    SERVICE_SPARK_PLUGS: "mdi:flash",
    SERVICE_DIFFERENTIAL: "mdi:car-traction-control",
    SERVICE_FUEL_FILTER: "mdi:fuel",
    SERVICE_BATTERY: "mdi:car-battery",
    SERVICE_REGISTRATION: "mdi:card-account-details-outline",
    SERVICE_STATE_INSPECTION: "mdi:clipboard-check",
}

# Which interval axes apply: "miles", "time", "both"
SERVICE_INTERVAL_TYPE = {
    SERVICE_OIL: "both",
    SERVICE_TIRE_ROTATION: "both",
    SERVICE_INSPECTION: "both",
    SERVICE_WIPERS: "time",
    SERVICE_AIR_FILTER: "both",
    SERVICE_CABIN_FILTER: "both",
    SERVICE_BRAKE_FLUID: "both",
    SERVICE_COOLANT: "both",
    SERVICE_TRANSMISSION: "both",
    SERVICE_SPARK_PLUGS: "both",
    SERVICE_DIFFERENTIAL: "both",
    SERVICE_FUEL_FILTER: "both",
    SERVICE_BATTERY: "time",
    SERVICE_REGISTRATION: "time",
    SERVICE_STATE_INSPECTION: "time",
}

# Repair categories
REPAIR_CATEGORIES = {
    "suspension": "Suspension / steering",
    "brakes_front": "Brake pads – front",
    "brakes_rear": "Brake pads – rear",
    "rotors_front": "Rotors – front",
    "rotors_rear": "Rotors – rear",
    "alignment": "Alignment",
    "engine": "Engine",
    "transmission_drivetrain": "Transmission / drivetrain",
    "cooling": "Cooling system",
    "hvac": "Heating / A/C",
    "timing_belt": "Timing belt",
    "battery": "Battery",
    "starter_alternator": "Starter / alternator",
    "exhaust": "Exhaust",
    "electrical": "Electrical",
    "body_glass": "Body / glass",
    "other": "Other",
}

# Status thresholds (percent of interval used)
STATUS_DUE_PCT = 90

# HA service call names
HA_SERVICE_ADD_ENTRY = "add_service_entry"
HA_SERVICE_UPDATE_ODOMETER = "update_odometer"
HA_SERVICE_ADD_REPAIR = "add_repair"
HA_SERVICE_ADD_TIRE = "add_tire"
HA_SERVICE_ADD_FUEL = "add_fuel"

# Events
EVENT_DATA_UPDATED = f"{DOMAIN}_data_updated"

# Tires — US tread depth in 32nds of an inch
TIRE_POSITIONS = {
    "lf": "Left front",
    "rf": "Right front",
    "lr": "Left rear",
    "rr": "Right rear",
}
TIRE_WEAR_32NDS_PER_MILE = 1 / 5000   # ~1/32" per 5,000 miles
TIRE_WARN_32NDS = 4
TIRE_LEGAL_MIN_32NDS = 2
