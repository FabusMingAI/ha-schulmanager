/* Schulmanager-Karte für Home Assistant – Aufgaben und Mitteilungen pro Kind.
 * Wird von der Integration automatisch geladen. Verwendung im Dashboard:
 *   type: custom:schulmanager-card         # Aufgaben & Mitteilungen
 *   type: custom:schulmanager-termine      # Termine & Fristen mit Legende
 *   type: custom:schulmanager-stundenplan  # Stundenplan mit Vertretungen
 *   child: anna          # optional, ohne Angabe: alle Kinder
 *   view: week           # nur Stundenplan: mit Wochenansicht starten (Standard: Tag)
 */
(() => {
  const VERSION = "0.9.0";
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fmtDate = (iso) => {
    if (!iso) return "";
    const [y, m, d] = iso.slice(0, 10).split("-");
    return `${d}.${m}.${y}`;
  };
  const fmtShort = (iso) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.` : "");
  // Erscheinungsdatum im Portal: „29.09.“, mit Jahr in Dialogen und für frühere Schuljahre
  const schoolYear = (iso) => {
    const y = Number(iso.slice(0, 4));
    return Number(iso.slice(5, 7)) >= 8 ? y : y - 1;
  };
  const todayIso = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const fmtPub = (iso, full) => {
    if (!iso) return "";
    return full || schoolYear(iso) !== schoolYear(todayIso()) ? fmtDate(iso) : fmtShort(iso);
  };
  const datedTitle = (iso, title, full) => (iso ? `${fmtPub(iso, full)} · ${title}` : title);
  const daysText = (days) => {
    if (days === null || days === undefined) return "";
    if (days === 0) return "heute";
    if (days === 1) return "morgen";
    if (days === -1) return "seit gestern";
    if (days < 0) return `seit ${-days} Tagen`;
    return `in ${days} Tagen`;
  };
  const dueClass = (t) => {
    if (t.status === "erledigt" || t.days === null || t.days === undefined) return "";
    if (t.days < 0) return "over";
    if (t.days <= 1) return "soon";
    if (t.days <= 7) return "week";
    return "";
  };
  const STATUS = [
    ["offen", "Offen", "mdi:checkbox-blank-circle-outline"],
    ["in_arbeit", "In Arbeit", "mdi:progress-clock"],
    ["erledigt", "Erledigt", "mdi:check-circle"],
  ];
  const AMPEL = { rot: "Dringend", gelb: "Etwas offen", gruen: "Alles erledigt" };
  const LANG_ORDER = ["de", "en", "es", "ca"];
  const LANG_NAMES = { de: "Deutsch", en: "English", es: "Español", ca: "Català" };
  const isPdf = (f) => (f.content_type || "").includes("pdf") || String(f.name || "").toLowerCase().endsWith(".pdf");

  const STYLE = `
    :host { display:block; }
    ha-card { padding: 12px 0 4px; overflow:hidden; }
    .child + .child { border-top: 1px solid var(--divider-color); margin-top: 8px; padding-top: 12px; }
    .head { display:flex; align-items:center; gap:10px; padding: 0 16px 8px; }
    .dot { width:12px; height:12px; border-radius:50%; flex:none; }
    .dot.rot { background: var(--error-color, #db4437); }
    .dot.gelb { background: var(--warning-color, #ffa600); }
    .dot.gruen { background: var(--success-color, #43a047); }
    .name { font-size: 1.25em; font-weight: 500; }
    .sub { color: var(--secondary-text-color); font-size: .9em; }
    .chips { display:flex; flex-wrap:wrap; gap:6px; padding: 0 16px 8px; }
    .chip { font-size:.8em; padding:2px 8px; border-radius:10px; background: var(--secondary-background-color); color: var(--primary-text-color); }
    .chip.red { background: rgba(219,68,55,.15); color: var(--error-color,#db4437); }
    .tabs { display:flex; gap:4px; padding: 0 12px; border-bottom: 1px solid var(--divider-color); }
    .tab { background:none; border:none; padding:8px 10px; cursor:pointer; color: var(--secondary-text-color); font: inherit; border-bottom: 2px solid transparent; }
    .tab.on { color: var(--primary-color); border-bottom-color: var(--primary-color); font-weight:500; }
    .list { padding: 4px 0; }
    .row { display:flex; align-items:center; gap:10px; padding: 8px 16px; cursor:pointer; }
    .row:hover { background: var(--secondary-background-color); }
    .row .main { flex:1; min-width:0; }
    .row .t { white-space: nowrap; overflow:hidden; text-overflow: ellipsis; }
    .row .s { font-size:.82em; color: var(--secondary-text-color); white-space: nowrap; overflow:hidden; text-overflow: ellipsis; }
    .row.done .t { text-decoration: line-through; color: var(--secondary-text-color); }
    .row.unread .t { font-weight: 600; }
    .due { font-size:.82em; white-space:nowrap; color: var(--secondary-text-color); text-align:right; }
    .due.over, .due.soon { color: var(--error-color,#db4437); font-weight:600; }
    .due.week { color: var(--warning-color,#ffa600); }
    .st { --mdc-icon-size: 22px; color: var(--secondary-text-color); flex:none; }
    .st.in_arbeit { color: var(--warning-color,#ffa600); }
    .st.erledigt { color: var(--success-color,#43a047); }
    .ud { width:8px; height:8px; border-radius:50%; background: var(--primary-color); flex:none; }
    .ud.read { background: transparent; }
    .empty { padding: 16px; color: var(--secondary-text-color); }
    .foot { padding: 4px 16px 8px; font-size:.8em; color: var(--secondary-text-color); display:flex; justify-content:space-between; gap:8px; }
    .foot a { color: var(--primary-color); cursor:pointer; text-decoration:none; }

    .ov { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 9999; display:flex; align-items:center; justify-content:center; }
    .dlg { background: var(--card-background-color, #fff); color: var(--primary-text-color); width: min(760px, 96vw); max-height: 92vh; overflow:auto; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,.4); }
    @media (max-width: 600px) {
      .dlg { width:100vw; max-height:100vh; height:100vh; height:100dvh; border-radius:0; }
      .dh { padding-top: calc(16px + env(safe-area-inset-top, 0px)); }
      .x { font-size: 2em; padding: 4px 10px; }
    }
    .df { position: sticky; bottom: 0; background: inherit; border-top:1px solid var(--divider-color); padding: 10px 16px calc(10px + env(safe-area-inset-bottom, 0px)); display:flex; justify-content:center; }
    .df .btn { flex:1; max-width: 420px; justify-content:center; padding:10px 14px; }
    .dh { display:flex; align-items:flex-start; gap:10px; padding: 16px 16px 8px; position: sticky; top:0; background: inherit; z-index:1; border-bottom:1px solid var(--divider-color); }
    .dh h2 { margin:0; font-size: 1.2em; font-weight:500; flex:1; line-height:1.35; }
    .x { background:none; border:none; cursor:pointer; color: var(--secondary-text-color); font-size: 1.6em; line-height:1; padding:0 4px; }
    .db { padding: 12px 16px 20px; }
    .sec { margin: 14px 0; }
    .lbl { font-size:.78em; text-transform: uppercase; letter-spacing:.04em; color: var(--secondary-text-color); margin-bottom:6px; }
    .seg { display:flex; border:1px solid var(--divider-color); border-radius: 8px; overflow:hidden; }
    .seg button { flex:1; padding:10px 6px; border:none; background:none; cursor:pointer; font: inherit; color: var(--primary-text-color); display:flex; align-items:center; justify-content:center; gap:6px; }
    .seg button + button { border-left:1px solid var(--divider-color); }
    .seg button.on.offen { background: var(--secondary-background-color); font-weight:600; }
    .seg button.on.in_arbeit { background: rgba(255,166,0,.18); font-weight:600; }
    .seg button.on.erledigt { background: rgba(67,160,71,.18); font-weight:600; }
    .grid { display:grid; grid-template-columns: max-content 1fr; gap: 4px 12px; font-size:.95em; }
    .grid .k { color: var(--secondary-text-color); }
    .grid > span { overflow-wrap:anywhere; min-width:0; }
    .copy { cursor:pointer; color: var(--primary-color); margin-left:6px; font-size:.85em; }
    input[type=date] { -webkit-appearance:none; appearance:none; display:block; min-height:42px; max-width:100%; }
    textarea, input[type=date] { width:100%; box-sizing:border-box; font: inherit; color: var(--primary-text-color); background: var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:8px; }
    textarea { min-height: 80px; resize: vertical; }
    .btns { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
    .btn { border:1px solid var(--divider-color); background:none; border-radius: 18px; padding:6px 14px; cursor:pointer; font: inherit; color: var(--primary-text-color); text-decoration:none; display:inline-flex; align-items:center; gap:6px; }
    .btn.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
    .src { border:1px solid var(--divider-color); border-radius:10px; padding:12px; }
    .src h3 { margin:0 0 4px; font-size:1.05em; font-weight:500; }
    .summary { background: var(--secondary-background-color); border-radius:8px; padding:8px 10px; margin:8px 0; }
    .ltabs { display:flex; gap:4px; margin:8px 0 -4px; flex-wrap:wrap; }
    .ltab { border:none; background:none; cursor:pointer; font: inherit; font-size:.85em; padding:4px 10px; border-radius:8px 8px 0 0; color: var(--secondary-text-color); }
    .ltab.on { background: var(--secondary-background-color); color: var(--primary-text-color); font-weight:600; }
    .ltabs + .summary { border-top-left-radius:0; }
    .pv.fs iframe { height: 100vh; border-radius:0; margin:0; }
    .row .stx { font-size:.8em; color: var(--warning-color,#e08a00); margin-left:4px; }
    .info.tr { padding-top: 0; }
    .bar2 { height:4px; border-radius:2px; background: var(--divider-color); margin-top:4px; overflow:hidden; }
    .bar2 i { display:block; height:100%; background: var(--primary-color); }
    .grp { padding: 10px 16px 2px; font-size:.8em; text-transform:uppercase; letter-spacing:.04em; color: var(--secondary-text-color); }
    pre { white-space: pre-wrap; word-wrap: break-word; font-family: inherit; font-size:.92em; margin: 6px 0 0; max-height: 50vh; overflow:auto; }
    iframe { width:100%; height: 65vh; border:1px solid var(--divider-color); border-radius:8px; margin-top:8px; background:#fff; }
    details summary { cursor:pointer; color: var(--primary-color); margin-top:8px; }
    .saved { color: var(--success-color,#43a047); font-size:.85em; margin-left:8px; }
    .warn { color: var(--warning-color,#ffa600); font-size:.85em; }
    .tip { position: fixed; z-index: 10000; max-width: min(360px, 90vw); background: var(--card-background-color, #fff); color: var(--primary-text-color); border:1px solid var(--divider-color); border-radius: 10px; box-shadow: 0 6px 24px rgba(0,0,0,.35); padding: 10px 12px; font-size: .9em; line-height:1.4; pointer-events:none; }
    .tip b { display:block; margin-bottom:4px; font-weight:600; }
    .tip .k { color: var(--secondary-text-color); font-size:.85em; margin-top:6px; }
    .day { padding: 10px 16px 2px; font-size:.8em; text-transform:uppercase; letter-spacing:.04em; color: var(--secondary-text-color); }
    .day.today { color: var(--primary-color); font-weight:600; }
    .day.over { color: var(--error-color,#db4437); font-weight:600; }
    .ev { display:flex; align-items:flex-start; gap:10px; padding: 6px 16px; cursor:pointer; }
    .ev:hover { background: var(--secondary-background-color); }
    .ev .ic { width: 1.6em; text-align:center; flex:none; font-size:1.05em; line-height:1.4; }
    .ev .tm { width: 3.2em; flex:none; font-size:.85em; color: var(--secondary-text-color); line-height:1.6; }
    .ev .main { flex:1; min-width:0; }
    .ev .t { line-height:1.4; }
    .ev .hv { display:none; font-size:.85em; color: var(--secondary-text-color); margin-top:2px; }
    .ev.open .hv { display:block; }
    .ev .who { font-size:.75em; padding:1px 7px; border-radius:9px; color:#fff; flex:none; margin-top:2px; }
    .ev.entfall .t { color: var(--error-color,#db4437); }
    .ev.vertretung .t, .ev.raum .t { color: var(--warning-color,#e08a00); }
    .legend { border-top:1px solid var(--divider-color); margin-top:8px; padding: 8px 16px 6px; display:flex; flex-wrap:wrap; gap:4px 14px; font-size:.8em; color: var(--secondary-text-color); }
    .legend .lt { width:100%; text-transform:uppercase; letter-spacing:.04em; font-size:.9em; }
    .legend span { white-space:nowrap; }
    .legend i { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:4px; vertical-align:middle; }
    .bar { display:flex; gap:6px; padding: 0 16px 6px; flex-wrap:wrap; align-items:center; }
    .pill { border:1px solid var(--divider-color); background:none; border-radius:16px; padding:4px 12px; cursor:pointer; font: inherit; font-size:.85em; color: var(--primary-text-color); }
    .pill.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color,#fff); }
    .pill .n { display:inline-block; min-width:1.2em; margin-left:4px; border-radius:8px; background: var(--warning-color,#ffa600); color:#fff; font-size:.8em; padding:0 4px; }
    .pill.today { font-weight:600; }
    .les { display:flex; align-items:center; gap:10px; padding: 7px 16px; }
    .les + .les { border-top: 1px solid var(--divider-color); }
    .les .nr { width:1.8em; text-align:right; font-weight:600; flex:none; }
    .les .tm { width:6.6em; flex:none; font-size:.82em; color: var(--secondary-text-color); white-space:nowrap; }
    .les .main { flex:1; min-width:0; }
    .les .sj { font-weight:500; }
    .les .ln { font-size:.8em; color: var(--secondary-text-color); }
    .les .rm { font-size:.85em; color: var(--secondary-text-color); white-space:nowrap; }
    .les.now { background: rgba(3,169,244,.08); }
    .les.entfall .sj { text-decoration: line-through; color: var(--secondary-text-color); }
    .badge { display:inline-block; font-size:.75em; padding:1px 7px; border-radius:9px; margin-left:6px; vertical-align:middle; }
    .badge.entfall { background: rgba(219,68,55,.15); color: var(--error-color,#db4437); }
    .badge.vertretung, .badge.raum { background: rgba(255,166,0,.18); color: var(--warning-color,#e08a00); }
    .chg { font-size:.82em; color: var(--warning-color,#e08a00); margin-top:2px; }
    .les.entfall .chg { color: var(--error-color,#db4437); }
    .wk { overflow-x:auto; padding: 0 12px 4px; container-type: inline-size; }
    .wk table { border-collapse: collapse; width:100%; font-size:.82em; table-layout: fixed; }
    .wk th:first-child { width: 3.4em; }
    .wk td { overflow-wrap:break-word; hyphens:auto; }
    .wk .sh { display:none; }
    /* schmale Karten (z. B. halbe Spalte): kurze Fachnamen, kleinere Schrift – kein Querscrollen */
    @container (max-width: 640px) {
      .wk table { font-size:.74em; }
      .wk .lg { display:none; }
      .wk .sh { display:inline; }
      .wk th, .wk td { padding:3px 2px; }
      .wk th:first-child { width: 2.9em; }
    }
    @container (max-width: 380px) {
      .wk th .dt { display:none; }
    }
    .wk th, .wk td { border:1px solid var(--divider-color); padding:4px 5px; text-align:center; vertical-align:top; }
    .wk th { color: var(--secondary-text-color); font-weight:500; }
    .wk th.today { color: var(--primary-color); }
    .wk td.chg-entfall { background: rgba(219,68,55,.12); }
    .wk td.chg-vertretung, .wk td.chg-raum { background: rgba(255,166,0,.15); }
    .wk .r { color: var(--secondary-text-color); font-size:.9em; }
    .exam { margin: 4px 16px 6px; padding: 8px 10px; border-radius: 8px; background: rgba(142,36,170,.14); border-left: 3px solid #8e24aa; font-size:.9em; }
    .exam.test { background: rgba(30,136,229,.12); border-left-color: #1e88e5; }
    .exam b { font-weight:600; }
    .badge.exam-sa { background: rgba(142,36,170,.18); color: #ab47bc; }
    .badge.exam-test { background: rgba(30,136,229,.16); color: #42a5f5; }
    .les.has-exam { box-shadow: inset 3px 0 0 #8e24aa; }
    .les.has-test { box-shadow: inset 3px 0 0 #1e88e5; }
    .wk td.exam-sa { outline: 2px solid #8e24aa; outline-offset: -2px; }
    .wk td.exam-test { outline: 2px solid #1e88e5; outline-offset: -2px; }
    .pill .x { margin-left:2px; font-size:.8em; }
    .info { padding: 4px 16px 8px; font-size:.82em; color: var(--secondary-text-color); }
  `;

  class SchulmanagerCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._tab = {};
      this._data = null;
      this._dialog = null;
    }

    setConfig(config) {
      this._config = config || {};
    }

    static getStubConfig() {
      return {};
    }

    getCardSize() {
      return 8;
    }

    getGridOptions() {
      return { columns: 12, min_columns: 6 };
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (first) {
        this._load();
        this._subscribe();
      }
    }

    connectedCallback() {
      if (this._hass && !this._unsub) this._subscribe();
    }

    disconnectedCallback() {
      if (this._unsub) {
        this._unsub.then((u) => u && u()).catch(() => {});
        this._unsub = null;
      }
    }

    _subscribe() {
      if (this._unsub || !this._hass) return;
      this._unsub = this._hass.connection
        .subscribeMessage(() => {
          clearTimeout(this._deb);
          this._deb = setTimeout(() => this._load(true), 400);
        }, { type: "schulmanager/subscribe" })
        .catch(() => {
          this._unsub = null;
          return null;
        });
    }

    async _ws(msg) {
      return this._hass.callWS(msg);
    }

    async _call(service, data) {
      await this._hass.callService("schulmanager", service, data);
    }

    async _load(refreshDialog) {
      try {
        const msg = { type: "schulmanager/data" };
        if (this._config.child) msg.child = this._config.child;
        this._data = await this._ws(msg);
        this._error = null;
        this._retries = 0;
      } catch (e) {
        this._error = e.message || String(e);
        // z. B. während Home Assistant noch startet: automatisch erneut versuchen
        clearTimeout(this._retry);
        const wait = Math.min(30000, 3000 * ((this._retries = (this._retries || 0) + 1)));
        this._retry = setTimeout(() => {
          this._load(refreshDialog);
          this._subscribe();
        }, wait);
      }
      this._render();
      if (refreshDialog && this._dialog && !this._editing) this._reopen();
    }

    // ------------------------------------------------------------ Liste
    _render() {
      const root = this.shadowRoot;
      const keepDialog = root.querySelector(".ov");
      let html = `<style>${STYLE}</style><ha-card>`;
      if (this._config.title) html += `<h1 class="card-header" style="margin:0;padding:0 16px 8px">${esc(this._config.title)}</h1>`;
      if (this._error) html += /unknown command|not.*(loaded|set ?up)|nicht eingerichtet/i.test(this._error) ? `<div class="empty">Schulmanager startet noch – die Daten erscheinen gleich automatisch …</div>` : `<div class="empty">Schulmanager: ${esc(this._error)}</div>`;
      else if (!this._data) html += `<div class="empty">Lade …</div>`;
      else if (!this._data.children.length) html += `<div class="empty">Keine Kinder gefunden.</div>`;
      else {
        const tr = this._data.translation;
        if (tr && tr.total) html += `<div class="info tr">🌐 Zusammenfassungen werden übersetzt${tr.languages && tr.languages.length ? ` (${esc(tr.languages.join(", "))})` : ""}: ${tr.done} von ${tr.total}<div class="bar2"><i style="width:${Math.round((100 * tr.done) / tr.total)}%"></i></div></div>`;
        for (const c of this._data.children) html += this._childHtml(c);
      }
      html += `</ha-card>`;
      root.innerHTML = html;
      if (keepDialog) root.appendChild(keepDialog);
      root.querySelectorAll("[data-tab]").forEach((el) =>
        el.addEventListener("click", () => {
          this._tab[el.dataset.child] = el.dataset.tab;
          this._render();
        })
      );
      root.querySelectorAll("[data-task]").forEach((el) =>
        el.addEventListener("click", () => this._openTask(el.dataset.task))
      );
      root.querySelectorAll("[data-item]").forEach((el) =>
        el.addEventListener("click", () => this._openItem(el.dataset.item))
      );
      root.querySelectorAll("[data-readall]").forEach((el) =>
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          this._call("mark_read", { child: el.dataset.readall });
        })
      );
    }

    _childHtml(c) {
      const tab = this._tab[c.key] || "aufgaben";
      const open = c.tasks.filter((t) => t.status !== "erledigt");
      const done = c.tasks.filter((t) => t.status === "erledigt");
      const activeItems = c.items.filter((i) => i.status !== "erledigt");
      const doneItems = c.items.filter((i) => i.status === "erledigt");
      const chips = [];
      if (c.overdue) chips.push(`<span class="chip red">${c.overdue} überfällig</span>`);
      if (open.length) chips.push(`<span class="chip">${open.length} offen</span>`);
      if (c.payments_text) chips.push(`<span class="chip">💶 ${esc(c.payments_text)} zu zahlen</span>`);
      if (c.unread) chips.push(`<span class="chip">📬 ${c.unread} ungelesen</span>`);
      let body = "";
      if (tab === "aufgaben") body = this._taskList(open, "Keine offenen Aufgaben 🎉");
      else if (tab === "erledigt") {
        body = !done.length && !doneItems.length ? `<div class="empty">Noch nichts erledigt.</div>` : "";
        if (done.length) body += `${doneItems.length ? `<div class="grp">Aufgaben</div>` : ""}${this._taskList(done, "")}`;
        if (doneItems.length) body += `<div class="grp">Mitteilungen</div>${this._itemList(doneItems)}`;
      } else body = this._itemList(activeItems);
      return `
        <div class="child">
          <div class="head">
            <span class="dot ${esc(c.ampel)}" title="${esc(AMPEL[c.ampel] || "")}"></span>
            <div><div class="name">${esc(c.name)}</div>
            <div class="sub">${c.classname ? "Klasse " + esc(c.classname) + " · " : ""}${esc(c.school || "")}</div></div>
          </div>
          <div class="chips">${chips.join("")}</div>
          <div class="tabs">
            <button class="tab ${tab === "aufgaben" ? "on" : ""}" data-child="${esc(c.key)}" data-tab="aufgaben">Aufgaben (${open.length})</button>
            <button class="tab ${tab === "mitteilungen" ? "on" : ""}" data-child="${esc(c.key)}" data-tab="mitteilungen">Mitteilungen${c.unread ? ` (${c.unread} neu)` : ""}</button>
            <button class="tab ${tab === "erledigt" ? "on" : ""}" data-child="${esc(c.key)}" data-tab="erledigt">Erledigt</button>
          </div>
          <div class="list">${body}</div>
          ${tab === "mitteilungen" && c.unread ? `<div class="foot"><span></span><a data-readall="${esc(c.key)}">Alle als gelesen markieren</a></div>` : ""}
        </div>`;
    }

    _taskList(tasks, emptyText) {
      if (!tasks.length) return `<div class="empty">${emptyText}</div>`;
      return tasks
        .map((t) => {
          const st = STATUS.find((s) => s[0] === t.status) || STATUS[0];
          const sub = [t.amount_text ? "💶 " + t.amount_text : "", t.comment ? "💬 " + t.comment : "", t.item_title ? "aus: " + t.item_title : ""]
            .filter(Boolean)
            .join(" · ");
          const due = t.due
            ? `<div class="due ${dueClass(t)}">${fmtShort(t.due)}<br>${t.status === "erledigt" ? "" : daysText(t.days)}</div>`
            : "";
          return `<div class="row ${t.status === "erledigt" ? "done" : ""}" data-task="${esc(t.id)}">
              <ha-icon class="st ${esc(t.status)}" icon="${st[2]}" title="${st[1]}"></ha-icon>
              <div class="main"><div class="t">${esc(t.icon)} ${esc(datedTitle(t.published, t.title))}${t.has_files ? " 📎" : ""}</div>
              ${sub ? `<div class="s">${esc(sub)}</div>` : ""}</div>${due}</div>`;
        })
        .join("");
    }

    _itemList(items) {
      if (!items.length) return `<div class="empty">Keine Mitteilungen.</div>`;
      return items
        .map(
          (i) => `<div class="row ${i.read ? "" : "unread"} ${i.status === "erledigt" ? "done" : ""}" data-item="${esc(i.uid)}">
            <span class="ud ${i.read ? "read" : ""}"></span>
            <div class="main"><div class="t">${i.urgency === "hoch" && i.status !== "erledigt" ? "🔴 " : ""}${esc(i.title)}${i.files ? " 📎" : ""}${i.status === "in_arbeit" ? `<span class="stx">⏳ In Arbeit</span>` : ""}</div>
            <div class="s">${esc(i.kind_label)}${i.sender ? " · " + esc(i.sender) : ""}${i.summary ? " · " + esc(i.summary) : ""}</div></div>
            <div class="due">${fmtShort(i.sent)}${i.tasks_open ? `<br>${i.tasks_open} Aufg.` : ""}</div></div>`
        )
        .join("");
    }

    // ------------------------------------------------------------ Dialoge
    _reopen() {
      if (!this._dialog) return;
      if (this._dialog.type === "task") this._openTask(this._dialog.id, true);
      else this._openItem(this._dialog.id, true);
    }

    _closeDialog() {
      this._dialog = null;
      this._editing = false;
      const ov = this.shadowRoot.querySelector(".ov");
      if (ov) ov.remove();
    }

    _showDialog(title, bodyHtml, bind) {
      let ov = this.shadowRoot.querySelector(".ov");
      const scroll = ov ? ov.querySelector(".dlg").scrollTop : 0;
      if (!ov) {
        ov = document.createElement("div");
        ov.className = "ov";
        this.shadowRoot.appendChild(ov);
      }
      ov.innerHTML = `<div class="dlg" role="dialog" aria-modal="true">
          <div class="dh"><h2>${title}</h2><button class="x" title="Schließen">×</button></div>
          <div class="db">${bodyHtml}</div>
          <div class="df"><button class="btn primary close2">Schließen</button></div></div>`;
      ov.querySelector(".dlg").scrollTop = scroll;
      ov.onclick = (ev) => {
        if (ev.target === ov) this._closeDialog();
      };
      ov.querySelector(".x").onclick = () => this._closeDialog();
      ov.querySelector(".close2").onclick = () => this._closeDialog();
      if (!this._escBound) {
        this._escBound = true;
        window.addEventListener("keydown", (ev) => {
          if (ev.key === "Escape" && this._dialog) this._closeDialog();
        });
      }
      ov.querySelectorAll("[data-copy]").forEach((el) =>
        el.addEventListener("click", () => {
          navigator.clipboard?.writeText(el.dataset.copy);
          el.textContent = "kopiert ✓";
        })
      );
      ov.querySelectorAll("[data-task]").forEach((el) =>
        el.addEventListener("click", () => this._openTask(el.dataset.task))
      );
      ov.querySelectorAll("[data-preview]").forEach((el) =>
        el.addEventListener("click", () => {
          const box = ov.querySelector(".pv");
          box.innerHTML = `<iframe src="${esc(el.dataset.preview)}" title="Vorschau"></iframe>`;
        })
      );
      ov.querySelectorAll("[data-lang]").forEach((el) =>
        el.addEventListener("click", () => {
          this._lang = el.dataset.lang;
          ov.querySelectorAll("[data-lang]").forEach((t) => t.classList.toggle("on", t === el));
          ov.querySelectorAll("[data-langbox]").forEach((b) => (b.hidden = b.dataset.langbox !== this._lang));
        })
      );
      ov.querySelectorAll("[data-fs]").forEach((el) =>
        el.addEventListener("click", () => this._fullscreen(ov, el.dataset.fs))
      );
      ov.querySelectorAll("[data-print]").forEach((el) =>
        el.addEventListener("click", () => this._print(el.dataset.print))
      );
      if (bind) bind(ov);
    }

    _sourceHtml(item, opts = {}) {
      if (!item) return "";
      const files = item.files || [];
      const pdf = files.find(isPdf);
      const text = (item.body || "").trim();
      const fileText = (item.text || "").trim();
      return `<div class="src">
          <div class="lbl">${esc(item.kind_label)} · ${fmtDate(item.sent)}${item.sender ? " · " + esc(item.sender) : ""}</div>
          <h3>${esc(item.title)}</h3>
          ${this._summaryHtml(item)}
          <div class="btns">
            ${files.map((f) => `<a class="btn" href="${esc(f.url)}" target="_blank" rel="noopener">📄 ${esc(f.name)}</a>${isPdf(f) ? `<button class="btn" data-print="${esc(f.url)}" title="${esc(f.name)} drucken">🖨 Drucken</button>` : ""}`).join("")}
            ${pdf ? `<button class="btn" data-preview="${esc(pdf.url)}">👁 PDF hier anzeigen</button><button class="btn" data-fs="${esc(pdf.url)}">⛶ Vollbild</button>` : ""}
            ${item.url ? `<a class="btn" href="${esc(item.url)}" target="_blank" rel="noopener">↗ Im Eltern-Portal</a>` : ""}
          </div>
          <div class="pv">${opts.preview && pdf ? `<iframe src="${esc(pdf.url)}" title="Vorschau"></iframe>` : ""}</div>
          ${text ? `<details ${opts.openText ? "open" : ""}><summary>Text der Mitteilung</summary><pre>${esc(text)}</pre></details>` : ""}
          ${fileText ? `<details><summary>Text aus der PDF</summary><pre>${esc(fileText)}</pre></details>` : ""}
        </div>`;
    }

    // PDF im Vollbild; ohne Vollbild-Unterstützung (z. B. iPhone) in neuem Tab öffnen
    _fullscreen(ov, url) {
      const box = ov.querySelector(".pv");
      let frame = box.querySelector("iframe");
      if (!frame) {
        box.innerHTML = `<iframe src="${esc(url)}" title="Vorschau"></iframe>`;
        frame = box.querySelector("iframe");
      }
      const req = box.requestFullscreen || box.webkitRequestFullscreen;
      if (!req) {
        window.open(url, "_blank", "noopener");
        return;
      }
      const leave = () => {
        if (!(document.fullscreenElement || document.webkitFullscreenElement)) {
          box.classList.remove("fs");
          document.removeEventListener("fullscreenchange", leave);
          document.removeEventListener("webkitfullscreenchange", leave);
        }
      };
      box.classList.add("fs");
      document.addEventListener("fullscreenchange", leave);
      document.addEventListener("webkitfullscreenchange", leave);
      Promise.resolve(req.call(box)).catch(() => {
        box.classList.remove("fs");
        window.open(url, "_blank", "noopener");
      });
    }

    // PDF drucken: unsichtbar laden und den Druckdialog des Browsers öffnen
    _print(url) {
      const old = document.getElementById("schulmanager-print");
      if (old) old.remove();
      const frame = document.createElement("iframe");
      frame.id = "schulmanager-print";
      frame.style.cssText = "position:fixed;right:0;bottom:0;width:1px;height:1px;border:0;opacity:0;";
      frame.src = url;
      frame.onload = () => {
        try {
          frame.contentWindow.focus();
          frame.contentWindow.print();
        } catch (e) {
          window.open(url, "_blank", "noopener");
        }
      };
      document.body.appendChild(frame);
    }

    // KI-Zusammenfassung mit einem Reiter je Sprache (Einstellung „Sprachen der KI-Zusammenfassung“)
    _summaryHtml(item) {
      const langs = Object.keys(item.summaries || {}).sort((a, b) => LANG_ORDER.indexOf(a) - LANG_ORDER.indexOf(b));
      if (!langs.length) return item.summary ? `<div class="summary">🤖 ${esc(item.summary)}</div>` : "";
      this._lang = this._lang && langs.includes(this._lang) ? this._lang : langs[0];
      const tabs = langs.length > 1
        ? `<div class="ltabs">${langs.map((l) => `<button class="ltab ${l === this._lang ? "on" : ""}" data-lang="${esc(l)}">${esc(LANG_NAMES[l] || l)}</button>`).join("")}</div>`
        : "";
      return `${tabs}${langs.map((l) => `<div class="summary" data-langbox="${esc(l)}" ${l === this._lang ? "" : "hidden"}>🤖 ${esc(item.summaries[l])}</div>`).join("")}`;
    }

    async _openTask(id, silent) {
      let t;
      try {
        t = await this._ws({ type: "schulmanager/task", task_id: id });
      } catch (e) {
        if (!silent) console.error("Schulmanager:", e);
        return;
      }
      this._dialog = { type: "task", id };
      const pay = t.amount_text
        ? `<div class="sec"><div class="lbl">Zahlung</div><div class="grid">
            <span class="k">Betrag</span><span><b>${esc(t.amount_text)}</b></span>
            ${t.payee ? `<span class="k">Empfänger</span><span>${esc(t.payee)}</span>` : ""}
            ${t.iban ? `<span class="k">IBAN</span><span>${esc(t.iban)}<span class="copy" data-copy="${esc(t.iban)}">kopieren</span></span>` : ""}
            ${t.reference ? `<span class="k">Verwendungszweck</span><span>${esc(t.reference)}<span class="copy" data-copy="${esc(t.reference)}">kopieren</span></span>` : ""}
          </div></div>`
        : "";
      const others = (t.item?.tasks || []).filter((o) => o.id !== t.id);
      const body = `
        <div class="sec"><div class="lbl">Status</div>
          <div class="seg">${STATUS.map(
            ([k, label, icon]) => `<button class="${k} ${t.status === k ? "on" : ""}" data-status="${k}"><ha-icon icon="${icon}"></ha-icon>${label}</button>`
          ).join("")}</div></div>
        <div class="sec"><div class="lbl">Fällig</div>
          <input type="date" class="due-in" value="${esc(t.due || "")}">
          ${t.due && t.status !== "erledigt" ? `<div class="sub" style="margin-top:4px">${daysText(t.days)}</div>` : ""}
        </div>
        ${pay}
        ${t.details ? `<div class="sec"><div class="lbl">Details</div><div>${esc(t.details)}</div></div>` : ""}
        ${t.source === "regeln" ? `<div class="warn">⚠️ Ohne KI erkannt – bitte prüfen.</div>` : ""}
        <div class="sec"><div class="lbl">Kommentar</div>
          <textarea class="cm" placeholder="z. B. „Überwiesen am 2.10.“ oder „Zettel liegt im Ranzen“">${esc(t.comment || "")}</textarea>
          <div class="btns"><button class="btn primary save-cm">Kommentar speichern</button><span class="saved-msg">${t.comment_at ? `<span class="sub">zuletzt ${fmtDate(t.comment_at)}</span>` : ""}</span></div>
        </div>
        ${t.item ? `<div class="sec"><div class="lbl">Quelle</div>${this._sourceHtml(t.item, { openText: !t.item.files.length })}</div>` : `<div class="sec sub">Eigene Aufgabe (ohne Mitteilung).</div>`}
        ${others.length ? `<div class="sec"><div class="lbl">Weitere Aufgaben aus dieser Mitteilung</div>${this._taskList(others, "")}</div>` : ""}
      `;
      this._showDialog(`${esc(t.icon)} ${esc(datedTitle(t.published, t.title, true))}${t.child_name ? ` <span class="sub">· ${esc(t.child_name)}</span>` : ""}`, body, (ov) => {
        ov.querySelectorAll("[data-status]").forEach((b) =>
          b.addEventListener("click", async () => {
            await this._call("update_task", { task_id: t.id, status: b.dataset.status });
            this._openTask(t.id, true);
          })
        );
        ov.querySelector(".due-in").addEventListener("change", async (ev) => {
          await this._call("update_task", { task_id: t.id, due: ev.target.value || null });
        });
        const ta = ov.querySelector(".cm");
        ta.addEventListener("focus", () => (this._editing = true));
        ta.addEventListener("blur", () => (this._editing = false));
        ov.querySelector(".save-cm").addEventListener("click", async () => {
          await this._call("update_task", { task_id: t.id, comment: ta.value });
          this._editing = false;
          ov.querySelector(".saved-msg").innerHTML = `<span class="saved">gespeichert ✓</span>`;
        });
      });
    }

    async _openItem(uid, silent) {
      let i;
      try {
        i = await this._ws({ type: "schulmanager/item", item_id: uid });
      } catch (e) {
        if (!silent) console.error("Schulmanager:", e);
        return;
      }
      this._dialog = { type: "item", id: uid };
      if (!i.read && !silent) {
        this._call("mark_read", { item_id: uid });
        i.read = true;
      }
      const status = i.status || "offen";
      const body = `
        <div class="sec"><div class="lbl">Status</div>
          <div class="seg">${STATUS.map(
            ([k, label, icon]) => `<button class="${k} ${status === k ? "on" : ""}" data-istatus="${k}"><ha-icon icon="${icon}"></ha-icon>${label}</button>`
          ).join("")}</div></div>
        ${this._sourceHtml(i, { openText: true })}
        <div class="sec"><div class="lbl">Aufgaben aus dieser Mitteilung</div>
          ${i.tasks.length ? this._taskList(i.tasks, "") : `<div class="sub">Keine – reine Information.</div>`}</div>
        <div class="btns">
          <button class="btn mark">${i.read ? "Als ungelesen markieren" : "Als gelesen markieren"}</button>
          <button class="btn re">🤖 Neu auswerten</button>
        </div>`;
      this._showDialog(`${i.urgency === "hoch" && status !== "erledigt" ? "🔴 " : ""}${esc(datedTitle(i.sent && i.sent.slice(0, 10), i.title, true))}`, body, (ov) => {
        ov.querySelectorAll("[data-istatus]").forEach((b) =>
          b.addEventListener("click", async () => {
            const next = b.dataset.istatus;
            await this._call("update_item", { item_id: uid, status: next });
            // erledigt: Mitteilung wandert in den Reiter „Erledigt“, Dialog schließen
            if (next === "erledigt") this._closeDialog();
            else this._openItem(uid, true);
          })
        );
        ov.querySelector(".mark").addEventListener("click", async () => {
          await this._call("mark_read", { item_id: uid, read: !i.read });
          this._openItem(uid, true);
        });
        ov.querySelector(".re").addEventListener("click", async (ev) => {
          await this._call("reanalyze", { item_id: uid });
          ev.target.textContent = "wird ausgewertet …";
        });
      });
    }
  }


  // ================================================================
  // Gemeinsame Helfer für Termine und Stundenplan
  // ================================================================
  const WD = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
  const WD_LONG = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];
  const CHILD_COLORS = ["#1e88e5", "#8e24aa", "#00897b", "#f4511e", "#6d4c41"];
  const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const parseDay = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
  };
  const addDays = (iso, n) => {
    const d = parseDay(iso);
    d.setDate(d.getDate() + n);
    return isoDay(d);
  };
  const dayLabel = (iso, today) => {
    const d = parseDay(iso);
    const base = `${WD[d.getDay()]} ${fmtShort(iso)}`;
    if (iso === today) return `Heute · ${base}`;
    if (iso === addDays(today, 1)) return `Morgen · ${base}`;
    if (iso === addDays(today, -1)) return `Gestern · ${base}`;
    return base;
  };
  // Fächer-Kürzel bayerischer Schulen -> Klartext (nur zur Anzeige)
  const SUBJECTS = {
    D: "Deutsch", M: "Mathematik", E: "Englisch", F: "Französisch", L: "Latein", Sp: "Spanisch", Spa: "Spanisch", It: "Italienisch", Gr: "Griechisch",
    Ku: "Kunst", Mu: "Musik", Geo: "Geographie", G: "Geschichte", B: "Biologie", C: "Chemie", Ph: "Physik", Inf: "Informatik", NuT: "Natur und Technik",
    WR: "Wirtschaft und Recht", Sk: "Sozialkunde", PuG: "Politik und Gesellschaft", Ev: "Ev. Religion", K: "Kath. Religion", Eth: "Ethik",
    Sm: "Sport (Jungen)", Sw: "Sport (Mädchen)", S: "Sport", Smw: "Sport", IntÜ: "Intensivierung", Int: "Intensivierung", Ch: "Chor", Orch: "Orchester",
    Wi: "Wirtschaftsinformatik", Chor: "Chor", TTennis: "Tischtennis", Schwim: "Schwimmen", Fussball: "Fußball", Stimm: "Stimmbildung", Schach: "Schach", Big: "Big Band", Theater: "Theater", MbO: "Berufsorientierung", BO: "Berufsorientierung", P: "Profilfach", PSem: "P-Seminar", WSem: "W-Seminar", KR: "Klassenleiterstunde", KLS: "Klassenleiterstunde",
  };
  // Kürzel -> Klartext, z. B. "B" -> "Biologie", "MInt" -> "Mathematik (Intensivierung)",
  // "Sm/Sw" -> "Sport", "Ev/K/Eth" -> "Religion / Ethik", "Ku_Wahl_Foto" -> "Kunst (Wahlfach)"
  const SUFFIX = [[/Wahl/i, "Wahlfach"], [/^Int|_Int/, "Intensivierung"], [/(^|_)F[öo]/, "Förderunterricht"]];
  const SPORT = new Set(["Sm", "Sw", "S", "Smw"]);
  const RELIGION = new Set(["Ev", "K", "Eth"]);
  const partName = (p) => {
    if (SPORT.has(p)) return "Sport";
    if (SUBJECTS[p]) return SUBJECTS[p];
    // iF / iL = Intensivierung, PhÜ = Übung
    if (/^i[A-ZÄÖÜ]/.test(p) && SUBJECTS[p.slice(1)]) return `${SUBJECTS[p.slice(1)]} (Intensivierung)`;
    if (/Ü$/.test(p) && SUBJECTS[p.slice(0, -1)]) return `${SUBJECTS[p.slice(0, -1)]} (Übung)`;
    // Fach + Zusatz direkt angehängt (MInt) oder mit Unterstrich (D_Fö, Ku_Wahl_Foto, NuT_NWw)
    const m = p.match(/^([A-ZÄÖÜ][a-zäöü]*?)_?((?:Int|Wahl|F[öo])\w*)?(?:_(.*))?$/);
    const pieces = p.split("_");
    for (const [base, rest] of [[pieces[0], pieces.slice(1).join("_")], [m && m[1], m && (m[2] || "")]]) {
      if (!base || !(SUBJECTS[base] || SPORT.has(base))) continue;
      const name = SPORT.has(base) ? "Sport" : SUBJECTS[base];
      const extra = SUFFIX.find(([re]) => re.test(rest || ""));
      if (base === "Big" && /^Band/.test(rest || "")) return /Wahl/i.test(rest) ? "Big Band (Wahlfach)" : "Big Band";
      return extra ? `${name} (${extra[1]})` : name;
    }
    const wahl = p.match(/^(.*?)_Wahl/i);
    if (wahl) return `${wahl[1].replace(/_/g, " ")} (Wahlfach)`;
    return p.replace(/_/g, " ");
  };
  const fullName = (s) => {
    if (!s) return "";
    const parts = String(s).split("/").map((x) => x.trim()).filter(Boolean);
    if (parts.length > 1 && parts.every((x) => RELIGION.has(x))) return "Religion / Ethik";
    return [...new Set(parts.map(partName))].join(" / ");
  };
  // Kurzform für die Wochenansicht in schmalen Karten, z. B. "Mathematik (Intensivierung)" -> "Mathe Int."
  const SHORT = [
    [/\s*\(Intensivierung\)/g, " Int."], [/\s*\(Übung\)/g, " Ü"], [/\s*\(Wahlfach\)/g, " (W)"], [/\s*\(Förderunterricht\)/g, " Förd."],
    [/Mathematik/g, "Mathe"], [/Englisch/g, "Engl."], [/Französisch/g, "Franz."], [/Spanisch/g, "Span."], [/Italienisch/g, "Ital."],
    [/Griechisch/g, "Griech."], [/Biologie/g, "Bio"], [/Geschichte/g, "Gesch."], [/Geographie/g, "Geo"], [/Informatik/g, "Info"],
    [/Natur und Technik/g, "NuT"], [/Religion \/ Ethik/g, "Reli/Eth"], [/Ev\. Religion/g, "Ev. Reli"], [/Kath\. Religion/g, "Kath. Reli"],
    [/Berufsorientierung/g, "BO"], [/Wirtschaft und Recht/g, "WR"], [/Wirtschaftsinformatik/g, "WIn"], [/Sozialkunde/g, "Sozi"],
    [/Politik und Gesellschaft/g, "PuG"], [/Klassenleiterstunde/g, "KL-Std."], [/Intensivierung/g, "Int."], [/Stimmbildung/g, "Stimmb."],
    [/Tischtennis/g, "TT"], [/Schwimmen/g, "Schwimm."], [/Orchester/g, "Orch."], [/Profilfach/g, "Profil"],
  ];
  const shortName = (s) => SHORT.reduce((t, [re, r]) => t.replace(re, r), fullName(s)).replace(/\s*\/\s*/g, "/");
  const lessonNums = (txt) => {
    const nums = String(txt || "").match(/\d+/g) || [];
    if (nums.length === 2 && /-|–|bis/.test(txt)) {
      const out = [];
      for (let i = Number(nums[0]); i <= Number(nums[1]); i++) out.push(String(i));
      return out;
    }
    return nums;
  };
  const clip = (t, n = 280) => {
    const v = String(t || "").replace(/\s+/g, " ").trim();
    return v.length > n ? v.slice(0, n - 1).trimEnd() + " …" : v;
  };
  const room = (r) => String(r || "").replace(/^\/+|\/+$/g, "");
  // Änderung in Klartext, ohne Kürzel und ohne Stundennummer (steht schon in der Zeile)
  const changeText = (e) => {
    const subj = fullName(e.subject || e.old_subject || "");
    const info = String(e.info || "").trim();
    const r = room(e.room);
    let t;
    if (e.kind === "entfall") {
      t = `${subj ? subj + " " : ""}entfällt`;
      if (info && !/^entf[aä]llt\.?$/i.test(info)) t += ` – ${info}`;
      return t;
    }
    if (e.kind === "raum") {
      t = `Raumänderung${r ? ": Raum " + r : ""}`;
      if (info && !/^raum(änderung|wechsel)\.?$/i.test(info)) t += ` – ${info}`;
      return t;
    }
    t = `Vertretung${subj ? ": " + subj : ""}${e.substitute ? " bei " + e.substitute : ""}${r ? ", Raum " + r : ""}`;
    if (e.old_subject) t += ` (statt ${fullName(e.old_subject)})`;
    if (info) t += ` – ${info}`;
    return t;
  };
  // Schulaufgaben/Tests einem Fach im Stundenplan zuordnen (Wortanfang, 6 Buchstaben)
  const stems = (txt) =>
    String(txt || "").toLowerCase().replace(/[^a-zäöüß]+/g, " ").split(" ").filter((w) => w.length >= 4).map((w) => w.slice(0, 6));
  const sameSubject = (examSubject, lessonSubject) => {
    const a = stems(examSubject);
    const b = stems(fullName(lessonSubject) + " " + lessonSubject);
    return a.some((x) => b.includes(x));
  };
  const EXAM_LABEL = { schulaufgabe: ["📝", "Schulaufgabe", "exam-sa"], test: ["✏️", "Test", "exam-test"] };
  const KIND_LABEL = { entfall: "entfällt", vertretung: "Vertretung", raum: "Raum" };
  const KIND_SHORT = { entfall: "entfällt", vertretung: "Vertr.", raum: "Raum" };
  const EXAM_SHORT = { schulaufgabe: "SA", test: "Test" };

  class SchulmanagerTermineCard extends SchulmanagerCard {
    getCardSize() {
      return 6;
    }

    _render() {
      const root = this.shadowRoot;
      const keepDialog = root.querySelector(".ov");
      let html = `<style>${STYLE}</style><ha-card>`;
      if (this._config.title) html += `<h1 class="card-header" style="margin:0;padding:0 16px 8px">${esc(this._config.title)}</h1>`;
      if (this._error) html += /unknown command|not.*(loaded|set ?up)|nicht eingerichtet/i.test(this._error) ? `<div class="empty">Schulmanager startet noch …</div>` : `<div class="empty">Schulmanager: ${esc(this._error)}</div>`;
      else if (!this._data) html += `<div class="empty">Lade …</div>`;
      else html += this._agendaHtml();
      html += `</ha-card>`;
      root.innerHTML = html;
      if (keepDialog) root.appendChild(keepDialog);
      this._bindAgenda();
    }

    _agendaHtml() {
      const d = this._data;
      const today = d.today || isoDay(new Date());
      const multi = d.children.length > 1;
      const colors = {};
      d.children.forEach((c, i) => (colors[c.key] = CHILD_COLORS[i % CHILD_COLORS.length]));
      this._events = {};
      let events = [];
      for (const c of d.children) for (const e of c.events || []) {
        const key = `${c.key}:${e.uid}`;
        this._events[key] = { ...e, child: c.key, child_name: c.name };
        events.push(this._events[key]);
      }
      const range = this._range || "2w";
      const limit = range === "2w" ? addDays(today, 14) : addDays(today, 400);
      const shown = events.filter((e) => e.date <= limit);
      const hidden = events.length - shown.length;
      shown.sort((a, b) => (a.date + (a.time || "")).localeCompare(b.date + (b.time || "")) || a.title.localeCompare(b.title));
      const groups = [];
      const over = shown.filter((e) => (e.until || e.date) < today && e.task_id);
      if (over.length) groups.push(["over", "Überfällig", over]);
      const byDay = {};
      for (const e of shown) {
        if ((e.until || e.date) < today && e.task_id) continue;
        const day = e.date < today && e.until ? today : e.date;
        (byDay[day] = byDay[day] || []).push(e);
      }
      for (const day of Object.keys(byDay).sort()) groups.push([day, dayLabel(day, today), byDay[day]]);
      let html = `<div class="bar">
          <button class="pill ${range === "2w" ? "on" : ""}" data-range="2w">Nächste 2 Wochen</button>
          <button class="pill ${range === "all" ? "on" : ""}" data-range="all">Alle${range === "2w" && hidden ? ` (+${hidden})` : ""}</button>
        </div>`;
      if (!groups.length) html += `<div class="empty">Keine Termine ${range === "2w" ? "in den nächsten zwei Wochen" : "geplant"} 🎉</div>`;
      for (const [key, label, list] of groups) {
        html += `<div class="day ${key === today ? "today" : key === "over" ? "over" : ""}">${esc(label)}</div>`;
        for (const e of list) {
          const sub = e.category === "entfall" || e.category === "vertretung" || e.category === "raum" ? e.category : "";
          const time = e.time ? e.time : e.until ? "bis " + fmtShort(e.until) : "";
          html += `<div class="ev ${sub}" data-ev="${esc(e.child + ":" + e.uid)}">
              <span class="ic">${esc(e.icon)}</span>
              <span class="tm">${esc(time)}</span>
              <div class="main"><div class="t">${esc(e.title)}</div>
                <div class="hv">${esc(clip(e.hover))}</div></div>
              ${multi ? `<span class="who" style="background:${colors[e.child]}">${esc(e.child_name)}</span>` : ""}
            </div>`;
        }
      }
      // Legende: alle Kategorien, die in der Liste vorkommen
      const legend = d.legend || {};
      const cats = [...new Set(shown.map((e) => e.category))];
      const order = Object.keys(legend);
      cats.sort((a, b) => order.indexOf(a) - order.indexOf(b));
      if (cats.length || multi) {
        html += `<div class="legend"><span class="lt">Legende</span>`;
        for (const c of cats) {
          const [icon, label] = legend[c] || ["📅", c];
          html += `<span>${esc(icon)} ${esc(label)}</span>`;
        }
        if (multi) for (const c of d.children) html += `<span><i style="background:${colors[c.key]}"></i>${esc(c.name)}</span>`;
        html += `</div><div class="info">Maus auf einen Eintrag halten (am Handy antippen) zeigt die Kurzbeschreibung.</div>`;
      }
      return html;
    }

    _bindAgenda() {
      const root = this.shadowRoot;
      root.querySelectorAll("[data-range]").forEach((el) =>
        el.addEventListener("click", () => {
          this._range = el.dataset.range;
          this._render();
        })
      );
      const touch = window.matchMedia && window.matchMedia("(hover: none)").matches;
      root.querySelectorAll("[data-ev]").forEach((el) => {
        const ev = this._events[el.dataset.ev];
        if (!ev) return;
        if (!touch) {
          el.addEventListener("mouseenter", (m) => this._showTip(ev, m));
          el.addEventListener("mousemove", (m) => this._moveTip(m));
          el.addEventListener("mouseleave", () => this._hideTip());
        }
        el.addEventListener("click", () => {
          this._hideTip();
          if (touch && !el.classList.contains("open") && ev.hover) {
            el.classList.add("open");
            return;
          }
          if (ev.task_id) this._openTask(ev.task_id);
          else if (ev.item_uid) this._openItem(ev.item_uid);
          else el.classList.toggle("open");
        });
      });
    }

    _showTip(ev, m) {
      this._hideTip();
      const legend = (this._data && this._data.legend) || {};
      const cat = legend[ev.category];
      const tip = document.createElement("div");
      tip.className = "tip";
      const when = `${dayLabel(ev.date, this._data.today)}${ev.time ? ", " + ev.time + (ev.time_end && ev.time_end !== ev.time ? "–" + ev.time_end : "") : ""}${ev.until ? " bis " + fmtShort(ev.until) : ""}`;
      tip.innerHTML = `<b>${esc(ev.icon)} ${esc(ev.title)}</b>
        ${ev.hover ? `<div>${esc(clip(ev.hover))}</div>` : ""}
        <div class="k">${esc(when)}${ev.location ? " · " + esc(ev.location) : ""}${cat ? " · " + esc(cat[1]) : ""}${this._data.children.length > 1 ? " · " + esc(ev.child_name) : ""}</div>
        ${ev.task_id || ev.item_uid ? `<div class="k">Klicken für Details</div>` : ""}`;
      this.shadowRoot.appendChild(tip);
      this._tip = tip;
      this._moveTip(m);
    }

    _moveTip(m) {
      const tip = this._tip;
      if (!tip) return;
      const pad = 14;
      let x = m.clientX + pad;
      let y = m.clientY + pad;
      const r = tip.getBoundingClientRect();
      if (x + r.width > window.innerWidth - 8) x = Math.max(8, m.clientX - r.width - pad);
      if (y + r.height > window.innerHeight - 8) y = Math.max(8, m.clientY - r.height - pad);
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
    }

    _hideTip() {
      if (this._tip) this._tip.remove();
      this._tip = null;
    }
  }

  class SchulmanagerStundenplanCard extends SchulmanagerCard {
    getCardSize() {
      return 7;
    }

    _render() {
      const root = this.shadowRoot;
      const keepDialog = root.querySelector(".ov");
      let html = `<style>${STYLE}</style><ha-card>`;
      if (this._config.title) html += `<h1 class="card-header" style="margin:0;padding:0 16px 8px">${esc(this._config.title)}</h1>`;
      if (this._error) html += /unknown command|not.*(loaded|set ?up)|nicht eingerichtet/i.test(this._error) ? `<div class="empty">Schulmanager startet noch …</div>` : `<div class="empty">Schulmanager: ${esc(this._error)}</div>`;
      else if (!this._data) html += `<div class="empty">Lade …</div>`;
      else if (!this._data.children.length) html += `<div class="empty">Keine Kinder gefunden.</div>`;
      else for (const c of this._data.children) html += this._planHtml(c);
      html += `</ha-card>`;
      root.innerHTML = html;
      if (keepDialog) root.appendChild(keepDialog);
      root.querySelectorAll("[data-day]").forEach((el) =>
        el.addEventListener("click", () => {
          this._sel = { ...(this._sel || {}), [el.dataset.child]: el.dataset.day };
          this._week = { ...(this._week || {}), [el.dataset.child]: false };
          this._render();
        })
      );
      root.querySelectorAll("[data-week]").forEach((el) =>
        el.addEventListener("click", () => {
          this._week = { ...(this._week || {}), [el.dataset.week]: !this._isWeek(el.dataset.week) };
          this._render();
        })
      );
    }

    // Wochenansicht aktiv? Ohne Klick gilt die Einstellung `view: week` der Karte.
    _isWeek(key) {
      const w = (this._week || {})[key];
      return w === undefined ? this._config.view === "week" : w;
    }

    // Datum des nächsten (oder heutigen) Tages mit diesem Wochentag
    _dateFor(weekday, today) {
      const t = parseDay(today);
      let diff = weekday - (t.getDay() || 7);
      if (diff < 0) diff += 7;
      return addDays(today, diff);
    }

    _defaultDay(c, today) {
      const now = new Date();
      const wd = parseDay(today).getDay();
      const todays = c.timetable.filter((l) => l.weekday === wd);
      const last = todays.length ? todays[todays.length - 1].end : null;
      const hhmm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
      if (wd >= 1 && wd <= 5 && todays.length && (!last || hhmm < last)) return today;
      // sonst: nächster Schultag
      for (let i = 1; i <= 7; i++) {
        const iso = addDays(today, i);
        const w = parseDay(iso).getDay();
        if (w >= 1 && w <= 5 && (c.timetable.some((l) => l.weekday === w) || !c.timetable.length)) return iso;
      }
      return today;
    }

    _planHtml(c) {
      const today = this._data.today || isoDay(new Date());
      const subst = c.substitutions || { days: [] };
      const byDate = {};
      for (const d of subst.days || []) byDate[d.date] = d.entries;
      const sel = (this._sel || {})[c.key] || this._defaultDay(c, today);
      const multi = this._data.children.length > 1;
      const exams = {};
      for (const e of c.events || []) if (EXAM_LABEL[e.category]) (exams[e.date] = exams[e.date] || []).push(e);
      this._exams = exams;
      let html = `<div class="child">`;
      if (multi || this._config.show_name) html += `<div class="head"><div class="name">${esc(c.name)}</div>${c.classname ? `<div class="sub">Klasse ${esc(c.classname)}</div>` : ""}</div>`;
      // Tagesauswahl Mo–Fr (+ Tage aus dem Vertretungsplan)
      html += `<div class="bar">`;
      for (let wd = 1; wd <= 5; wd++) {
        const iso = this._dateFor(wd, today);
        const n = (byDate[iso] || []).length;
        const ex = (exams[iso] || []).map((e) => EXAM_LABEL[e.category][0]).join("");
        const tip = [`${WD_LONG[wd]} ${fmtShort(iso)}`, ...(exams[iso] || []).map((e) => e.title)].join("\n");
        html += `<button class="pill ${iso === sel && !this._isWeek(c.key) ? "on" : ""} ${iso === today ? "today" : ""}" data-child="${esc(c.key)}" data-day="${iso}" title="${esc(tip)}">${WD[wd]}${ex ? `<span class="x">${ex}</span>` : ""}${n ? `<span class="n">${n}</span>` : ""}</button>`;
      }
      html += `<button class="pill ${this._isWeek(c.key) ? "on" : ""}" data-week="${esc(c.key)}">Woche</button></div>`;

      const soon = Object.keys(exams).filter((d) => d >= today && d <= addDays(today, 13)).sort();
      if (soon.length) {
        html += `<div class="info">${soon.map((d) => exams[d].map((e) => `${EXAM_LABEL[e.category][0]} ${dayLabel(d, today).split(" · ")[0]}: ${esc(e.subject ? fullName(e.subject) : e.title)}`).join(" · ")).join(" · ")}</div>`;
      }
      if (this._isWeek(c.key)) html += this._weekHtml(c, today, byDate);
      else html += this._dayHtml(c, sel, today, byDate[sel] || [], byDate.hasOwnProperty(sel));

      // Vertretungsplan-Überblick
      const days = (subst.days || []).filter((d) => d.date >= today);
      if (!subst.available && !days.length) {
        html += `<div class="info">Vertretungsplan: im Portal nicht verfügbar oder noch nicht abgerufen.</div>`;
      } else {
        const parts = days.map((d) => `${dayLabel(d.date, today).split(" · ")[0]}: ${d.entries.length ? d.entries.length + " Änderung" + (d.entries.length > 1 ? "en" : "") : "keine Änderungen"}`);
        html += `<div class="info">🔁 Vertretungsplan${subst.stand ? ` (Stand ${esc(subst.stand)})` : ""}: ${esc(parts.join(" · ") || "keine Einträge")}</div>`;
      }
      html += `</div>`;
      return html;
    }

    _dayHtml(c, iso, today, entries, known) {
      const wd = parseDay(iso).getDay();
      const lessons = c.timetable.filter((l) => l.weekday === wd);
      const used = new Set();
      const changes = (nr) =>
        entries.filter((e, i) => {
          const hit = lessonNums(e.lesson).includes(String(nr));
          if (hit) used.add(i);
          return hit;
        });
      const now = new Date();
      const hhmm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
      let html = `<div class="day ${iso === today ? "today" : ""}">${esc(dayLabel(iso, today))}${known && !entries.length ? " · keine Vertretungen" : ""}</div>`;
      const dayExams = (this._exams || {})[iso] || [];
      for (const e of dayExams) {
        const [icon, label] = EXAM_LABEL[e.category];
        html += `<div class="exam ${e.category === "test" ? "test" : ""}">${icon} <b>${label}</b>: ${esc(e.title)}</div>`;
      }
      const examFor = (subject) => dayExams.find((e) => e.subject && sameSubject(e.subject, subject));
      if (!c.timetable.length) html += `<div class="empty">Noch kein Stundenplan abgerufen.</div>`;
      else if (!lessons.length) html += `<div class="empty">Kein Unterricht laut Stundenplan.</div>`;
      for (const l of lessons) {
        const ch = changes(l.lesson);
        const kind = ch.some((e) => e.kind === "entfall") ? "entfall" : ch.length ? ch[0].kind : "";
        const isNow = iso === today && l.start && l.end && hhmm >= l.start && hhmm < l.end;
        const long = fullName(l.subject);
        const ex = examFor(l.subject);
        const exCls = ex ? (ex.category === "test" ? "has-test" : "has-exam") : "";
        const exBadge = ex ? `<span class="badge ${EXAM_LABEL[ex.category][2]}">${EXAM_LABEL[ex.category][0]} ${EXAM_LABEL[ex.category][1]}</span>` : "";
        html += `<div class="les ${kind} ${exCls} ${isNow ? "now" : ""}">
            <span class="nr">${esc(l.lesson)}.</span>
            <span class="tm">${l.start ? esc(l.start) + "–" + esc(l.end || "") : ""}</span>
            <div class="main"><div class="sj" title="${esc(l.subject)}">${esc(long)}${kind ? `<span class="badge ${kind}">${KIND_LABEL[kind] || kind}</span>` : ""}${exBadge}</div>
              ${ch.map((e) => `<div class="chg">${esc(changeText(e))}</div>`).join("")}</div>
            <span class="rm">${esc(room(l.room))}</span>
          </div>`;
      }
      const rest = entries.filter((e, i) => !used.has(i));
      if (rest.length) {
        html += `<div class="day">Weitere Änderungen</div>`;
        for (const e of rest) html += `<div class="les ${e.kind}"><span class="nr">${esc(e.lesson || "")}.</span><div class="main"><div class="sj">${esc(fullName(e.subject || e.old_subject || ""))}<span class="badge ${e.kind}">${KIND_LABEL[e.kind] || e.kind}</span></div><div class="chg">${esc(changeText(e))}</div></div><span class="rm">${esc(e.room || "")}</span></div>`;
      }
      return html;
    }

    _weekHtml(c, today, byDate) {
      if (!c.timetable.length) return `<div class="empty">Noch kein Stundenplan abgerufen.</div>`;
      const nums = [...new Set(c.timetable.map((l) => l.lesson))].sort((a, b) => Number(a) - Number(b));
      const times = {};
      for (const l of c.timetable) if (l.start && !times[l.lesson]) times[l.lesson] = l.start;
      let html = `<div class="wk"><table lang="de"><tr><th></th>`;
      const dates = [1, 2, 3, 4, 5].map((wd) => this._dateFor(wd, today));
      dates.forEach((iso, i) => (html += `<th class="${iso === today ? "today" : ""}">${WD[i + 1]} <span class="dt">${fmtShort(iso)}</span></th>`));
      html += `</tr>`;
      for (const nr of nums) {
        html += `<tr><th>${esc(nr)}.<div class="r">${esc(times[nr] || "")}</div></th>`;
        dates.forEach((iso, i) => {
          const l = c.timetable.find((x) => x.weekday === i + 1 && x.lesson === nr);
          const ch = (byDate[iso] || []).filter((e) => lessonNums(e.lesson).includes(String(nr)));
          const kind = ch.some((e) => e.kind === "entfall") ? "entfall" : ch.length ? ch[0].kind : "";
          const ex = l && ((this._exams || {})[iso] || []).find((e) => e.subject && sameSubject(e.subject, l.subject));
          const exCls = ex ? " " + EXAM_LABEL[ex.category][2] : "";
          html += `<td class="${kind ? "chg-" + kind : ""}${exCls}" title="${esc(ch.map(changeText).join("\n") || l?.subject || "")}">${l ? `<span class="lg">${esc(fullName(l.subject))}</span><span class="sh">${esc(shortName(l.subject))}</span>` + `<div class="r">${esc(room(l.room))}</div>` : ""}${kind ? `<div class="r"><span class="lg">${KIND_LABEL[kind]}</span><span class="sh">${KIND_SHORT[kind] || KIND_LABEL[kind]}</span></div>` : ""}${ex ? `<div class="r">${EXAM_LABEL[ex.category][0]} <span class="lg">${EXAM_LABEL[ex.category][1]}</span><span class="sh">${EXAM_SHORT[ex.category]}</span></div>` : ""}</td>`;
        });
        html += `</tr>`;
      }
      return html + `</table></div><div class="info">Farbig: Änderung laut Vertretungsplan (rot = entfällt, orange = Vertretung/Raum). Umrandet: 📝 Schulaufgabe (lila), ✏️ Test (blau).</div>`;
    }
  }

  const define = (tag, cls, name, description) => {
    if (customElements.get(tag)) return;
    customElements.define(tag, cls);
    window.customCards = window.customCards || [];
    window.customCards.push({ type: tag, name, description, preview: false });
  };
  define("schulmanager-card", SchulmanagerCard, "Schulmanager", "Aufgaben und Mitteilungen aus dem Eltern-Portal – klickbar mit Status, Kommentar und PDF.");
  define("schulmanager-termine", SchulmanagerTermineCard, "Schulmanager: Termine", "Termine, Fristen und Vertretungen mit KI-Kurzbeschreibung und Legende.");
  define("schulmanager-stundenplan", SchulmanagerStundenplanCard, "Schulmanager: Stundenplan", "Stundenplan mit Vertretungen und Ausfällen.");
  console.info(`%c SCHULMANAGER-CARD %c ${VERSION} `, "background:#03a9f4;color:#fff", "");
})();
