/*
 * Vehicle Service Card — bundled with the Vehicle Service Manager (US) integration.
 *
 * type: custom:vehicle-service-card
 * device: <device id>            # pick the vehicle in the visual editor
 * name: My Outback               # optional, defaults to the device name
 * image: /local/cars/outback.jpg # optional, landscape photo
 * upcoming_miles: 500            # optional
 * upcoming_months: 1             # optional
 * max_items: 3                   # optional
 */

const CARD_VERSION = "2.0.0";
const DOMAIN = "vehicle_service";

const DEFAULTS = { upcoming_miles: 500, upcoming_months: 1, max_items: 3 };

const STATUS = {
  ok: { label: "OK", color: "var(--success-color, #43a047)" },
  watch: { label: "OK", color: "var(--success-color, #43a047)" },
  soon: { label: "Soon", color: "var(--warning-color, #ffa000)" },
  due: { label: "Due", color: "var(--warning-color, #ffa000)" },
  overdue: { label: "Overdue", color: "var(--error-color, #db4437)" },
};

// Keep in sync with REPAIR_CATEGORIES in const.py
const REPAIR_CATEGORIES = [
  ["suspension", "Suspension / steering"],
  ["brakes_front", "Brake pads – front"],
  ["brakes_rear", "Brake pads – rear"],
  ["rotors_front", "Rotors – front"],
  ["rotors_rear", "Rotors – rear"],
  ["alignment", "Alignment"],
  ["engine", "Engine"],
  ["transmission_drivetrain", "Transmission / drivetrain"],
  ["cooling", "Cooling system"],
  ["hvac", "Heating / A/C"],
  ["timing_belt", "Timing belt"],
  ["battery", "Battery"],
  ["starter_alternator", "Starter / alternator"],
  ["exhaust", "Exhaust"],
  ["electrical", "Electrical"],
  ["body_glass", "Body / glass"],
  ["other", "Other"],
];

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtNum = (n) => Math.round(Number(n)).toLocaleString();

const fmtDate = (iso, withYear) => {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  const opts = { month: "short", day: "numeric" };
  if (withYear || d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString(undefined, opts);
};

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

/* ── Data helpers ─────────────────────────────────────────────────────────── */

function vehicleIdFor(hass, config) {
  if (config.vehicle_id) return config.vehicle_id;
  if (!config.device || !hass.entities) return null;
  for (const ent of Object.values(hass.entities)) {
    if (ent.device_id === config.device && ent.platform === DOMAIN) {
      const vid = hass.states[ent.entity_id]?.attributes?.vehicle_id;
      if (vid) return vid;
    }
  }
  return null;
}

function readVehicle(hass, config) {
  const vid = vehicleIdFor(hass, config);
  if (!vid) return null;

  const states = Object.values(hass.states).filter(
    (s) => s.attributes?.vehicle_id === vid && s.entity_id.startsWith("sensor.")
  );
  const odometer = states.find((s) => s.attributes.device_class === "distance");
  const deviceId =
    config.device || (odometer && hass.entities?.[odometer.entity_id]?.device_id);
  const device = deviceId ? hass.devices?.[deviceId] : undefined;
  const deviceName = device?.name_by_user || device?.name || "";

  const services = states
    .filter((s) => s.attributes.service_id)
    .map((s) => {
      const a = s.attributes;
      let label = a.friendly_name || a.service_id;
      if (deviceName && label.startsWith(`${deviceName} `)) label = label.slice(deviceName.length + 1);
      return {
        entityId: s.entity_id,
        id: a.service_id,
        label: label.charAt(0).toUpperCase() + label.slice(1),
        icon: a.icon || "mdi:car-wrench",
        status: s.state,
        action: a.action || "replace",
        pct: Number(a.percentage) || 0,
        milesLeft: a.miles_left,
        monthsLeft: a.months_left,
        nextOdo: a.next_due_odometer,
        nextDate: a.next_due_date,
        lastDate: a.last_service_date,
        lastOdo: a.last_service_odometer,
        note: a.note,
      };
    });

  return {
    vid,
    name: config.name || deviceName || "Vehicle",
    odometer: odometer ? Number(odometer.state) : null,
    unit: odometer?.attributes?.unit_of_measurement || "mi",
    services,
  };
}

function urgency(svc, cfg) {
  // < 1 means inside the "upcoming" window; negative means overdue
  const parts = [];
  if (svc.milesLeft != null) parts.push(svc.milesLeft / Math.max(cfg.upcoming_miles, 1));
  if (svc.monthsLeft != null) parts.push(svc.monthsLeft / Math.max(cfg.upcoming_months, 0.01));
  return parts.length ? Math.min(...parts) : Infinity;
}

function upcoming(vehicle, cfg) {
  return vehicle.services
    .map((s) => ({ ...s, urgency: s.status === "overdue" ? Math.min(urgency(s, cfg), 0) : urgency(s, cfg) }))
    .filter((s) => s.urgency <= 1)
    .sort((a, b) => a.urgency - b.urgency);
}

function dueText(svc, cfg, unit) {
  const milesU = svc.milesLeft != null ? svc.milesLeft / Math.max(cfg.upcoming_miles, 1) : Infinity;
  const monthsU = svc.monthsLeft != null ? svc.monthsLeft / Math.max(cfg.upcoming_months, 0.01) : Infinity;
  const byMiles = milesU <= monthsU;
  if (byMiles && svc.milesLeft != null) {
    return svc.milesLeft < 0
      ? `Overdue by ${fmtNum(-svc.milesLeft)} ${unit}`
      : `Due in ${fmtNum(svc.milesLeft)} ${unit}`;
  }
  if (svc.nextDate) {
    return svc.monthsLeft < 0 ? `Overdue since ${fmtDate(svc.nextDate)}` : `Due ${fmtDate(svc.nextDate)}`;
  }
  return STATUS[svc.status]?.label || "";
}

/* ── Shared styles ────────────────────────────────────────────────────────── */

const BASE_CSS = `
  :host { --vsc-radius: 12px; --vsc-gap: 16px; }
  * { box-sizing: border-box; }
  .btn {
    font: inherit; font-weight: 500; font-size: 14px; cursor: pointer;
    border-radius: 999px; padding: 10px 16px; min-height: 40px;
    border: 1px solid var(--divider-color, rgba(127,127,127,.3));
    background: transparent; color: var(--primary-text-color);
    display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    transition: background-color .15s ease;
  }
  .btn:hover { background: var(--secondary-background-color, rgba(127,127,127,.08)); }
  .btn:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .btn.primary {
    background: var(--primary-color); border-color: var(--primary-color);
    color: var(--text-primary-color, #fff);
  }
  .btn.primary:hover { filter: brightness(1.08); }
  .btn[disabled] { opacity: .6; cursor: default; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .muted { color: var(--secondary-text-color); }
  ha-icon { --mdc-icon-size: 20px; }
`;

/* ── Card ─────────────────────────────────────────────────────────────────── */

class VehicleServiceCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "device", required: true, selector: { device: { filter: { integration: DOMAIN } } } },
        { name: "name", selector: { text: {} } },
        { name: "image", selector: { text: {} } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "upcoming_miles", selector: { number: { min: 0, max: 20000, step: 100, mode: "box", unit_of_measurement: "mi" } } },
            { name: "upcoming_months", selector: { number: { min: 0, max: 24, step: 1, mode: "box", unit_of_measurement: "months" } } },
            { name: "max_items", selector: { number: { min: 1, max: 10, step: 1, mode: "box" } } },
          ],
        },
      ],
      computeLabel: (s) =>
        ({
          device: "Vehicle",
          name: "Name (optional)",
          image: "Image URL (optional, e.g. /local/cars/outback.jpg)",
          upcoming_miles: "Show items due within (miles)",
          upcoming_months: "…or within (months)",
          max_items: "Max items shown",
        })[s.name],
    };
  }

  static getStubConfig(hass) {
    const ent = Object.values(hass?.entities || {}).find((e) => e.platform === DOMAIN && e.device_id);
    return { device: ent?.device_id || "", ...DEFAULTS };
  }

  setConfig(config) {
    if (!config.device && !config.vehicle_id) throw new Error("Pick a vehicle (device).");
    this._config = { ...DEFAULTS, ...config };
    this._sig = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 6, min_columns: 4, rows: "auto" };
  }

  _render() {
    if (!this._config || !this._hass) return;
    const vehicle = readVehicle(this._hass, this._config);
    // Only re-render when something this card shows has changed
    const sig = JSON.stringify([vehicle, this._config]);
    if (sig === this._sig) return;
    this._sig = sig;
    this._vehicle = vehicle;

    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const cfg = this._config;

    if (!vehicle) {
      this.shadowRoot.innerHTML = `<style>${BASE_CSS}${CARD_CSS}</style>
        <ha-card><div class="body"><div class="empty">Vehicle not found. Edit the card and pick a vehicle.</div></div></ha-card>`;
      return;
    }

    const items = upcoming(vehicle, cfg);
    const shown = items.slice(0, cfg.max_items);
    const more = items.length - shown.length;
    const odo = vehicle.odometer != null && !Number.isNaN(vehicle.odometer) ? fmtNum(vehicle.odometer) : "—";

    const image = cfg.image
      ? `<img class="photo" src="${esc(cfg.image)}" alt="${esc(vehicle.name)}" loading="lazy">`
      : `<div class="photo placeholder"><ha-icon icon="mdi:car-side"></ha-icon></div>`;

    const rows = shown.length
      ? shown
          .map(
            (s) => `
          <button class="row" data-service="${esc(s.id)}" title="Log ${esc(s.label)}">
            <span class="row-icon"><ha-icon icon="${esc(s.icon)}"></ha-icon></span>
            <span class="row-main">
              <span class="row-label">${esc(s.label)}${s.action === "inspect" ? ' <span class="tag">Inspect</span>' : ""}</span>
              <span class="row-sub ${s.status === "overdue" ? "overdue" : "muted"}">${esc(dueText(s, cfg, vehicle.unit))}</span>
            </span>
            <span class="dot" style="background:${STATUS[s.status]?.color}"></span>
          </button>`
          )
          .join("") + (more > 0 ? `<div class="more muted">+${more} more</div>` : "")
      : `<div class="allgood"><ha-icon icon="mdi:check-circle-outline"></ha-icon><span>Nothing due in the next ${fmtNum(cfg.upcoming_miles)} ${esc(vehicle.unit)} or ${cfg.upcoming_months} month${cfg.upcoming_months === 1 ? "" : "s"}</span></div>`;

    this.shadowRoot.innerHTML = `
      <style>${BASE_CSS}${CARD_CSS}</style>
      <ha-card>
        <div class="body">
          <div class="name">${esc(vehicle.name)}</div>
          ${image}
          <div class="odo">
            <span class="odo-value">${odo}</span><span class="odo-unit">${esc(vehicle.unit)}</span>
          </div>
          <div class="odo-label muted">Current mileage</div>

          <div class="section-title">Upcoming maintenance</div>
          <div class="list">${rows}</div>

          <div class="actions">
            <button class="btn" id="all">See all maintenance</button>
            <button class="btn primary" id="log"><ha-icon icon="mdi:plus"></ha-icon>Log maintenance</button>
          </div>
        </div>
      </ha-card>`;

    this.shadowRoot.getElementById("all").addEventListener("click", () => this._open("all"));
    this.shadowRoot.getElementById("log").addEventListener("click", () => this._open("log"));
    this.shadowRoot.querySelectorAll(".row").forEach((el) =>
      el.addEventListener("click", () => this._open("log", [el.dataset.service]))
    );
    const img = this.shadowRoot.querySelector("img.photo");
    if (img) img.addEventListener("error", () => img.replaceWith(Object.assign(document.createElement("div"), {
      className: "photo placeholder", innerHTML: '<ha-icon icon="mdi:image-broken-variant"></ha-icon>',
    })));
  }

  _open(mode, preselect = []) {
    const dlg = document.createElement("vehicle-service-dialog");
    dlg.setup({ mode, card: this, preselect });
    document.body.appendChild(dlg);
  }
}

const CARD_CSS = `
  ha-card { overflow: hidden; }
  .body { padding: var(--vsc-gap); display: flex; flex-direction: column; container-type: inline-size; }
  .name { font-size: 20px; font-weight: 600; line-height: 1.3; margin-bottom: 12px; color: var(--primary-text-color); }
  .photo {
    width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block;
    border-radius: var(--vsc-radius);
    background: var(--secondary-background-color, rgba(127,127,127,.08));
  }
  .placeholder { display: flex; align-items: center; justify-content: center; color: var(--secondary-text-color); }
  .placeholder ha-icon { --mdc-icon-size: 64px; opacity: .45; }
  .odo { margin-top: 16px; display: flex; align-items: baseline; gap: 6px; color: var(--primary-text-color); }
  .odo-value { font-size: 32px; font-weight: 600; line-height: 1.1; font-variant-numeric: tabular-nums; letter-spacing: -.01em; }
  .odo-unit { font-size: 16px; color: var(--secondary-text-color); }
  .odo-label { font-size: 13px; margin-top: 2px; }
  .section-title {
    margin-top: 20px; margin-bottom: 4px; font-size: 13px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color);
  }
  .list { display: flex; flex-direction: column; }
  .row {
    all: unset; box-sizing: border-box; cursor: pointer; width: 100%;
    display: flex; align-items: center; gap: 12px; padding: 10px 8px; margin: 0 -8px; width: calc(100% + 16px);
    border-radius: 10px; color: var(--primary-text-color);
  }
  .row { position: relative; }
  .row + .row::before { content: ""; position: absolute; top: 0; left: 8px; right: 8px; border-top: 1px solid var(--divider-color, rgba(127,127,127,.15)); }
  .row:hover { background: var(--secondary-background-color, rgba(127,127,127,.08)); }
  .row:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  .row-icon { display: flex; flex: none; color: var(--secondary-text-color); }
  .row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .row-label { font-size: 15px; font-weight: 500; }
  .row-sub { font-size: 13px; font-variant-numeric: tabular-nums; }
  .row-sub.overdue { color: var(--error-color, #db4437); font-weight: 500; }
  .tag {
    font-size: 11px; font-weight: 500; padding: 1px 6px; border-radius: 6px; margin-left: 4px; vertical-align: 1px;
    background: var(--secondary-background-color, rgba(127,127,127,.12)); color: var(--secondary-text-color);
  }
  .more { font-size: 13px; padding: 6px 0 0; }
  .allgood { display: flex; align-items: center; gap: 10px; padding: 10px 0; color: var(--secondary-text-color); font-size: 14px; }
  .allgood ha-icon { color: var(--success-color, #43a047); flex: none; }
  .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 16px; }
  .empty { color: var(--secondary-text-color); padding: 8px 0; }
  @container (max-width: 340px) { .actions { grid-template-columns: 1fr; } }
`;

/* ── Dialog (appended to <body> so it can't be clipped by the dashboard) ──── */

class VehicleServiceDialog extends HTMLElement {
  setup({ mode, card, preselect }) {
    this._mode = mode;
    this._card = card;
    this._preselect = new Set(preselect);
    this._tab = mode === "history" ? "history" : "schedule";
    this._history = null;      // fetched when the History tab opens
  }

  connectedCallback() {
    this.attachShadow({ mode: "open" });
    this._render();
    this._onKey = (e) => e.key === "Escape" && this._close();
    document.addEventListener("keydown", this._onKey);
  }

  disconnectedCallback() {
    document.removeEventListener("keydown", this._onKey);
  }

  _close() {
    this.remove();
  }

  _render() {
    const v = this._card._vehicle;
    const isLog = this._mode === "log";
    this.shadowRoot.innerHTML = `
      <style>${BASE_CSS}${DIALOG_CSS}</style>
      <div class="scrim" part="scrim"></div>
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="t">
        <header>
          <div>
            <div class="title" id="t">${isLog ? "Log maintenance" : "All maintenance"}</div>
            <div class="subtitle muted">${esc(v.name)}</div>
          </div>
          <button class="icon-btn" id="x" aria-label="Close"><ha-icon icon="mdi:close"></ha-icon></button>
        </header>
        ${isLog ? "" : `<div class="tabs seg" role="tablist" aria-label="View">
            <button type="button" role="tab" data-tab="schedule" aria-selected="${this._tab === "schedule"}">Schedule</button>
            <button type="button" role="tab" data-tab="history" aria-selected="${this._tab === "history"}">History &amp; costs</button>
          </div>`}
        <div class="content">${isLog ? this._logForm(v) : this._tab === "history" ? this._historyView(v) : this._allList(v)}</div>
        ${isLog ? `<footer>
            <div class="error" id="err" role="alert"></div>
            <button class="btn" id="cancel">Cancel</button>
            <button class="btn primary" id="save">Save</button>
          </footer>` : `<footer><button class="btn primary" id="tolog"><ha-icon icon="mdi:plus"></ha-icon>Log maintenance</button></footer>`}
      </div>`;

    const $ = (id) => this.shadowRoot.getElementById(id);
    $("x").addEventListener("click", () => this._close());
    this.shadowRoot.querySelector(".scrim").addEventListener("click", () => this._close());
    if (isLog) {
      $("cancel").addEventListener("click", () => this._close());
      $("save").addEventListener("click", () => this._save());
      $("f").addEventListener("input", () => { $("err").textContent = ""; });
      this.shadowRoot.querySelectorAll('input[type="checkbox"]').forEach((c) =>
        c.addEventListener("change", () => this._syncLogForm())
      );
      this._syncLogForm();
    } else {
      this.shadowRoot.querySelectorAll(".tabs button").forEach((b) =>
        b.addEventListener("click", () => { this._tab = b.dataset.tab; this._render(); })
      );
      if (this._tab === "history" && this._history === null) this._loadHistory();
      $("tolog").addEventListener("click", () => { this._mode = "log"; this._render(); });
      this.shadowRoot.querySelectorAll(".item").forEach((el) =>
        el.addEventListener("click", () => { this._mode = "log"; this._preselect = new Set([el.dataset.service]); this._render(); })
      );
    }
  }

  async _loadHistory() {
    this._history = "loading";
    try {
      this._history = await this._card._hass.callWS({
        type: `${DOMAIN}/history`, vehicle_id: this._card._vehicle.vid,
      });
    } catch (e) {
      this._history = { error: e?.message || "Couldn't load history." };
    }
    if (this.isConnected && this._mode !== "log" && this._tab === "history") this._render();
  }

  _money(n) {
    const currency = this._card._hass?.config?.currency || "USD";
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(n) || 0);
    } catch (e) {
      return `$${(Number(n) || 0).toFixed(2)}`;
    }
  }

  _historyView(v) {
    const h = this._history;
    if (h === null || h === "loading") return `<div class="muted pad">Loading history…</div>`;
    if (h.error) return `<div class="error pad">${esc(h.error)}</div>`;
    const c = h.costs || {};
    const cat = c.by_category || {};
    const stat = (label, value) => `<div class="stat"><span class="stat-v">${value}</span><span class="stat-l muted">${label}</span></div>`;

    const summary = `
      <div class="summary">
        <div class="total"><span class="total-v">${this._money(c.total)}</span><span class="muted">Total spent to date</span></div>
        <div class="stats">
          ${stat("Maintenance", this._money(cat.maintenance))}
          ${stat("Repairs", this._money(cat.repairs))}
          ${stat("Tires", this._money(cat.tires))}
        </div>
        <div class="stats">
          ${stat("This year", this._money(c.ytd))}
          ${stat("Last 12 months", this._money(c.last_12_months))}
          ${stat("Per mile", c.per_mile != null ? this._money(c.per_mile) : "—")}
        </div>
      </div>`;

    const entries = h.entries || [];
    if (!entries.length) return summary + `<div class="muted pad">Nothing logged yet. Use Log maintenance to add the first entry.</div>`;

    const icon = { service: "mdi:wrench", repair: "mdi:tools", tires: "mdi:tire", visit: "mdi:car-wrench" };
    const kindLabel = { service: "Maintenance", repair: "Repair", tires: "Tires", visit: "Maintenance + repair" };
    const years = {};
    for (const e of entries) (years[(e.date || "").slice(0, 4) || "Undated"] ||= []).push(e);

    const groups = Object.entries(years)
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([year, list]) => {
        const sum = list.reduce((t, e) => t + (Number(e.cost) || 0), 0);
        const rows = list.map((e) => {
          const meta = [
            e.date ? fmtDate(e.date, true) : "",
            e.odometer ? `${fmtNum(e.odometer)} ${esc(v.unit)}` : "",
            e.shop ? esc(e.shop) : "",
          ].filter(Boolean).join(" · ");
          const extra = e.kind === "visit"
            ? [
                e.maintenance && e.repair ? `Maintenance ${this._money(e.maintenance.cost)} · Repair ${this._money(e.repair.cost)}` : "",
                e.notes || e.repair?.description || "",
              ].filter(Boolean).join("\n")
            : e.kind === "repair" ? (e.title !== e.category ? e.category : "")
            : e.kind === "tires" ? e.size : e.notes;
          return `
            <div class="h-row">
              <span class="h-icon"><ha-icon icon="${icon[e.kind]}"></ha-icon></span>
              <span class="h-main">
                <span class="h-title">${esc(e.title || kindLabel[e.kind])}</span>
                <span class="h-meta muted">${kindLabel[e.kind]}${meta ? " · " + meta : ""}</span>
                ${extra ? `<span class="h-extra muted">${esc(extra)}</span>` : ""}
              </span>
              <span class="h-cost${e.cost ? "" : " muted"}">${e.cost ? this._money(e.cost) : "—"}</span>
            </div>`;
        }).join("");
        return `<div class="year"><span>${esc(year)}</span><span class="muted">${this._money(sum)}</span></div>${rows}`;
      })
      .join("");

    return summary + groups;
  }

  _allList(v) {
    const cfg = this._card._config;
    const order = { overdue: 0, due: 1, soon: 2, watch: 3, ok: 4 };
    const list = [...v.services].sort((a, b) => (order[a.status] - order[b.status]) || (b.pct - a.pct));
    if (!list.length) return `<div class="muted">No items are tracked for this vehicle.</div>`;
    return list
      .map((s) => {
        const st = STATUS[s.status] || STATUS.ok;
        const next = [s.nextOdo != null ? `${fmtNum(s.nextOdo)} ${esc(v.unit)}` : "", s.nextDate ? fmtDate(s.nextDate, true) : ""]
          .filter(Boolean).join(" or ");
        const last = s.lastDate ? `Last ${fmtDate(s.lastDate, true)}${s.lastOdo ? ` at ${fmtNum(s.lastOdo)} ${esc(v.unit)}` : ""}` : "Not logged yet";
        return `
          <button class="item" data-service="${esc(s.id)}" title="Log ${esc(s.label)}">
            <span class="item-icon" style="color:${st.color}"><ha-icon icon="${esc(s.icon)}"></ha-icon></span>
            <span class="item-main">
              <span class="item-top">
                <span class="item-label">${esc(s.label)}${s.action === "inspect" ? ' <span class="tag">Inspect</span>' : ""}</span>
                <span class="chip" style="color:${st.color}">${s.status === "ok" || s.status === "watch" ? esc(dueText(s, cfg, v.unit)) : st.label}</span>
              </span>
              <span class="bar"><span style="width:${Math.min(100, s.pct)}%;background:${st.color}"></span></span>
              <span class="item-sub muted">${next ? `Due ${next}` : ""}${next ? " · " : ""}${last}</span>
            </span>
          </button>`;
      })
      .join("");
  }

  _logForm(v) {
    const odo = v.odometer != null && !Number.isNaN(v.odometer) ? Math.round(v.odometer) : "";
    const services = [...v.services].sort((a, b) => a.label.localeCompare(b.label));
    const chip = (name, value, icon, label, checked) => `
      <label class="check">
        <input type="checkbox" name="${name}" value="${esc(value)}" ${checked ? "checked" : ""}>
        ${icon ? `<ha-icon icon="${esc(icon)}"></ha-icon>` : ""}<span>${esc(label)}</span>
      </label>`;
    return `
      <form id="f" novalidate>
        <div class="grid2">
          <label class="field"><span>Date</span><input type="date" name="date" value="${todayIso()}" max="${todayIso()}" required></label>
          <label class="field"><span>Odometer (${esc(v.unit)})</span><input type="number" name="odometer" value="${odo}" min="0" step="1" inputmode="numeric" required></label>
        </div>
        <fieldset>
          <legend>Scheduled maintenance <span class="legend-hint">resets reminders</span></legend>
          <div class="checks">
            ${services.map((s) => chip("services", s.id, s.icon, s.label, this._preselect.has(s.id))).join("")}
          </div>
        </fieldset>
        <fieldset>
          <legend>Repairs <span class="legend-hint">one-off work</span></legend>
          <div class="checks">
            ${REPAIR_CATEGORIES.map(([k, l]) => chip("repairs", k, "", l, false)).join("")}
          </div>
        </fieldset>
        <label class="field"><span>Details</span>
          <textarea name="details" rows="2" placeholder="Optional, e.g. Replaced both front lower control arm assemblies"></textarea>
        </label>
        <label class="field"><span>Shop</span><input type="text" name="shop" placeholder="e.g. Valvoline, DIY" autocomplete="off"></label>
        <div class="grid2 costs">
          <label class="field" data-cost="maintenance"><span>Cost ($)</span><input type="number" name="maintenance_cost" min="0" step="0.01" inputmode="decimal" placeholder="0.00"></label>
          <label class="field" data-cost="repair"><span>Repair cost ($)</span><input type="number" name="repair_cost" min="0" step="0.01" inputmode="decimal" placeholder="0.00"></label>
        </div>
      </form>`;
  }

  /* Show one cost field, or a maintenance/repair split when both kinds are ticked */
  _syncLogForm() {
    const f = this.shadowRoot.getElementById("f");
    if (!f) return;
    const hasSvc = f.querySelectorAll('input[name="services"]:checked').length > 0;
    const hasRep = f.querySelectorAll('input[name="repairs"]:checked').length > 0;
    const both = hasSvc && hasRep;
    const m = f.querySelector('[data-cost="maintenance"]');
    const r = f.querySelector('[data-cost="repair"]');
    m.querySelector("span").textContent = both ? "Maintenance cost ($)" : "Cost ($)";
    r.hidden = !both;
    f.querySelector(".costs").classList.toggle("single", !both);
  }

  async _save() {
    const f = this.shadowRoot.getElementById("f");
    const err = this.shadowRoot.getElementById("err");
    const save = this.shadowRoot.getElementById("save");
    const data = new FormData(f);
    const services = data.getAll("services");
    const repairs = data.getAll("repairs");
    const odometer = parseInt(data.get("odometer"), 10);
    const date = data.get("date");
    const first = parseFloat(data.get("maintenance_cost")) || 0;
    const second = parseFloat(data.get("repair_cost")) || 0;

    err.textContent = "";
    if (!services.length && !repairs.length) return (err.textContent = "Select at least one item or repair.");
    if (!date) return (err.textContent = "Enter a date.");
    if (Number.isNaN(odometer) || odometer < 0) return (err.textContent = "Enter the odometer reading.");

    // With only repairs ticked, the single cost field is the repair cost
    const repairOnly = repairs.length && !services.length;
    save.disabled = true;
    save.textContent = "Saving…";
    try {
      await this._card._hass.callWS({
        type: `${DOMAIN}/log_visit`,
        vehicle_id: this._card._vehicle.vid,
        entry_date: date,
        odometer,
        services,
        repair_categories: repairs,
        details: (data.get("details") || "").trim(),
        shop: (data.get("shop") || "").trim(),
        maintenance_cost: repairOnly ? 0 : first,
        repair_cost: repairOnly ? first : repairs.length ? second : 0,
      });
      const what = services.length && repairs.length ? "Maintenance and repairs" : repairs.length ? "Repair" : "Maintenance";
      this._card.dispatchEvent(new CustomEvent("hass-notification", {
        bubbles: true, composed: true, detail: { message: `${what} logged` },
      }));
      this._close();
    } catch (e) {
      err.textContent = e?.message || "Couldn't save. Try again.";
      save.disabled = false;
      save.textContent = "Save";
    }
  }
}

const DIALOG_CSS = `
  :host { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center;
          font-family: var(--paper-font-body1_-_font-family, var(--ha-font-family-body, Roboto, system-ui, sans-serif));
          color: var(--primary-text-color); }
  .scrim { position: absolute; inset: 0; background: rgba(0,0,0,.45); animation: fade .15s ease; }
  .dialog {
    position: relative; width: min(520px, calc(100vw - 32px)); max-height: calc(100vh - 48px);
    display: flex; flex-direction: column; overflow: hidden;
    background: var(--card-background-color, var(--ha-card-background, #fff));
    border-radius: var(--ha-dialog-border-radius, 24px);
    box-shadow: 0 12px 40px rgba(0,0,0,.3); animation: pop .18s ease;
  }
  header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 20px 20px 12px; }
  .title { font-size: 20px; font-weight: 600; }
  .subtitle { font-size: 14px; margin-top: 2px; }
  .icon-btn { all: unset; cursor: pointer; display: flex; padding: 8px; margin: -6px -8px 0 0; border-radius: 50%; color: var(--secondary-text-color); }
  .icon-btn:hover { background: var(--secondary-background-color, rgba(127,127,127,.1)); }
  .icon-btn:focus-visible { outline: 2px solid var(--primary-color); }
  .content { padding: 4px 20px 8px; overflow-y: auto; }
  footer { display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding: 12px 20px 20px; border-top: 1px solid var(--divider-color, rgba(127,127,127,.15)); }
  .error { flex: 1; color: var(--error-color, #db4437); font-size: 13px; }

  .item { all: unset; box-sizing: border-box; cursor: pointer; display: flex; gap: 12px; width: 100%; padding: 12px 8px; margin: 0 -8px; width: calc(100% + 16px); border-radius: 10px; }
  .item { position: relative; }
  .item + .item::before { content: ""; position: absolute; top: 0; left: 8px; right: 8px; border-top: 1px solid var(--divider-color, rgba(127,127,127,.15)); }
  .item:hover { background: var(--secondary-background-color, rgba(127,127,127,.08)); }
  .item:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  .item-icon { padding-top: 1px; flex: none; }
  .item-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
  .item-top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .item-label { font-size: 15px; font-weight: 500; }
  .chip { font-size: 13px; font-weight: 500; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .bar { height: 4px; border-radius: 2px; background: var(--divider-color, rgba(127,127,127,.2)); overflow: hidden; }
  .bar span { display: block; height: 100%; border-radius: 2px; }
  .item-sub { font-size: 12px; font-variant-numeric: tabular-nums; }
  .tag { font-size: 11px; font-weight: 500; padding: 1px 6px; border-radius: 6px; margin-left: 4px; vertical-align: 1px;
         background: var(--secondary-background-color, rgba(127,127,127,.12)); color: var(--secondary-text-color); }

  form { display: flex; flex-direction: column; gap: 14px; padding-bottom: 8px; }
  .tabs { margin: 0 20px 8px; }
  .pad { padding: 12px 0; }
  .summary { padding: 4px 0 8px; border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.15)); margin-bottom: 4px; }
  .total { display: flex; flex-direction: column; gap: 2px; margin-bottom: 12px; font-size: 13px; }
  .total-v { font-size: 28px; font-weight: 600; letter-spacing: -.01em; font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
  .stat { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .stat-v { font-size: 15px; font-weight: 500; font-variant-numeric: tabular-nums; }
  .stat-l { font-size: 12px; }
  .year { display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; letter-spacing: .04em;
          padding: 14px 0 4px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .h-row { display: flex; gap: 12px; padding: 10px 0; align-items: flex-start; }
  .h-row + .h-row { border-top: 1px solid var(--divider-color, rgba(127,127,127,.15)); }
  .h-icon { color: var(--secondary-text-color); padding-top: 1px; flex: none; }
  .h-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .h-title { font-size: 15px; font-weight: 500; }
  .h-meta, .h-extra { font-size: 12px; font-variant-numeric: tabular-nums; }
  .h-extra { white-space: pre-wrap; }
  .h-cost { font-size: 15px; font-weight: 500; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .seg { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 4px; border-radius: 999px;
         background: var(--secondary-background-color, rgba(127,127,127,.1)); }
  .seg button { all: unset; box-sizing: border-box; text-align: center; cursor: pointer; padding: 8px 12px;
                border-radius: 999px; font-size: 14px; font-weight: 500; color: var(--secondary-text-color); }
  .seg button[aria-selected="true"] { background: var(--card-background-color, #fff); color: var(--primary-text-color);
                                      box-shadow: 0 1px 3px rgba(0,0,0,.15); }
  .seg button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
  select { font: inherit; font-size: 15px; color: var(--primary-text-color); background: transparent;
           border: 1px solid var(--divider-color, rgba(127,127,127,.3)); border-radius: 10px; padding: 10px 12px; width: 100%;
           color-scheme: light dark; }
  select:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; border-color: transparent; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--secondary-text-color); }
  input[type=text], input[type=number], input[type=date], textarea {
    font: inherit; font-size: 15px; color: var(--primary-text-color);
    background: transparent;
    border: 1px solid var(--divider-color, rgba(127,127,127,.3)); border-radius: 10px; padding: 10px 12px; width: 100%;
    color-scheme: light dark;
  }
  textarea { resize: vertical; }
  input:focus, textarea:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; border-color: transparent; }
  fieldset { border: 0; padding: 0; margin: 0; }
  legend { font-size: 13px; color: var(--secondary-text-color); margin-bottom: 8px; padding: 0; }
  .legend-hint { opacity: .75; margin-left: 4px; font-size: 12px; }
  .costs.single { grid-template-columns: 1fr; }
  .costs.single [data-cost="maintenance"] { max-width: calc(50% - 6px); }
  @media (max-width: 420px) { .costs.single [data-cost="maintenance"] { max-width: none; } }
  [hidden] { display: none !important; }
  .checks { display: flex; flex-wrap: wrap; gap: 8px; }
  .check { position: relative; display: inline-flex; align-items: center; gap: 6px; cursor: pointer; font-size: 14px;
           padding: 7px 12px 7px 10px; border-radius: 999px; border: 1px solid var(--divider-color, rgba(127,127,127,.3)); }
  .check input { position: absolute; opacity: 0; pointer-events: none; }
  .check ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); }
  .check:has(input:checked) { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .check:has(input:checked) ha-icon { color: inherit; }
  .check:has(input:focus-visible) { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  @media (max-width: 420px) { .grid2 { grid-template-columns: 1fr; } }
  @keyframes fade { from { opacity: 0; } }
  @keyframes pop { from { opacity: 0; transform: translateY(8px) scale(.98); } }
  @media (prefers-reduced-motion: reduce) { .scrim, .dialog { animation: none; } }
`;

/*
 * The integration loads this file early in page start-up. Home Assistant then
 * swaps in its own (scoped) custom-element registry, which doesn't see
 * elements defined before it existed. So define now, and keep re-checking for
 * a while; a fresh subclass is used each time because a registry won't accept
 * the same constructor twice.
 */
const ELEMENTS = {
  "vehicle-service-card": VehicleServiceCard,
  "vehicle-service-dialog": VehicleServiceDialog,
};

function registerElements() {
  let all = true;
  for (const [name, cls] of Object.entries(ELEMENTS)) {
    if (customElements.get(name)) continue;
    try {
      customElements.define(name, class extends cls {});
    } catch (e) {
      all = false;
    }
    if (!customElements.get(name)) all = false;
  }
  return all;
}

registerElements();
let registerTries = 0;
const registerTimer = setInterval(() => {
  registerElements();
  if (++registerTries >= 120) clearInterval(registerTimer); // ~60 s
}, 500);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "vehicle-service-card")) {
  window.customCards.push({
    type: "vehicle-service-card",
    name: "Vehicle Service",
    description: "Mileage, upcoming maintenance and logging for a vehicle.",
    preview: false,
    documentationURL: "https://github.com/toxictody1337/vehicle-service-manager#dashboard-card",
  });
}

console.info(`%c VEHICLE-SERVICE-CARD %c ${CARD_VERSION} `, "background:#1976d2;color:#fff;border-radius:3px 0 0 3px", "background:#555;color:#fff;border-radius:0 3px 3px 0");
