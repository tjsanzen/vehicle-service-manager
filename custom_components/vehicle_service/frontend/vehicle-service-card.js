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
    return { device: ent?.device_id || "" };
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
          .join("") + (more > 0 ? `<div class="more muted">+${more} more due soon</div>` : "")
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
        <div class="content">${isLog ? this._logForm(v) : this._allList(v)}</div>
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
      setTimeout(() => this.shadowRoot.querySelector("input")?.focus(), 0);
    } else {
      $("tolog").addEventListener("click", () => { this._mode = "log"; this._render(); });
      this.shadowRoot.querySelectorAll(".item").forEach((el) =>
        el.addEventListener("click", () => { this._mode = "log"; this._preselect = new Set([el.dataset.service]); this._render(); })
      );
    }
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
    return `
      <form id="f" novalidate>
        <div class="grid2">
          <label class="field"><span>Date</span><input type="date" name="date" value="${todayIso()}" max="${todayIso()}" required></label>
          <label class="field"><span>Odometer (${esc(v.unit)})</span><input type="number" name="odometer" value="${odo}" min="0" step="1" inputmode="numeric" required></label>
        </div>
        <fieldset>
          <legend>What was done</legend>
          <div class="checks">
            ${services.map((s) => `
              <label class="check">
                <input type="checkbox" name="services" value="${esc(s.id)}" ${this._preselect.has(s.id) ? "checked" : ""}>
                <ha-icon icon="${esc(s.icon)}"></ha-icon><span>${esc(s.label)}</span>
              </label>`).join("")}
          </div>
        </fieldset>
        <div class="grid2">
          <label class="field"><span>Shop</span><input type="text" name="shop" placeholder="e.g. Valvoline, DIY" autocomplete="off"></label>
          <label class="field"><span>Cost ($)</span><input type="number" name="cost" min="0" step="0.01" inputmode="decimal" placeholder="0.00"></label>
        </div>
        <label class="field"><span>Notes</span><textarea name="notes" rows="2" placeholder="Optional"></textarea></label>
      </form>`;
  }

  async _save() {
    const f = this.shadowRoot.getElementById("f");
    const err = this.shadowRoot.getElementById("err");
    const save = this.shadowRoot.getElementById("save");
    const data = new FormData(f);
    const services = data.getAll("services");
    const odometer = parseInt(data.get("odometer"), 10);
    const date = data.get("date");

    err.textContent = "";
    if (!services.length) return (err.textContent = "Select at least one item.");
    if (!date) return (err.textContent = "Enter a date.");
    if (Number.isNaN(odometer) || odometer < 0) return (err.textContent = "Enter the odometer reading.");

    save.disabled = true;
    save.textContent = "Saving…";
    try {
      await this._card._hass.callWS({
        type: `${DOMAIN}/add_service_entry`,
        vehicle_id: this._card._vehicle.vid,
        entry_date: date,
        odometer,
        services,
        shop: (data.get("shop") || "").trim(),
        cost: parseFloat(data.get("cost")) || 0,
        notes: (data.get("notes") || "").trim(),
      });
      this._card.dispatchEvent(new CustomEvent("hass-notification", {
        bubbles: true, composed: true, detail: { message: "Maintenance logged" },
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

if (!customElements.get("vehicle-service-card")) customElements.define("vehicle-service-card", VehicleServiceCard);
if (!customElements.get("vehicle-service-dialog")) customElements.define("vehicle-service-dialog", VehicleServiceDialog);

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
