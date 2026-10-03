/* Schulmanager-Karte für Home Assistant – Aufgaben und Mitteilungen pro Kind.
 * Wird von der Integration automatisch geladen. Verwendung im Dashboard:
 *   type: custom:schulmanager-card
 *   child: anna        # optional, ohne Angabe: alle Kinder
 */
(() => {
  const VERSION = "0.2.1";
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fmtDate = (iso) => {
    if (!iso) return "";
    const [y, m, d] = iso.slice(0, 10).split("-");
    return `${d}.${m}.${y}`;
  };
  const fmtShort = (iso) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.` : "");
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
    pre { white-space: pre-wrap; word-wrap: break-word; font-family: inherit; font-size:.92em; margin: 6px 0 0; max-height: 50vh; overflow:auto; }
    iframe { width:100%; height: 65vh; border:1px solid var(--divider-color); border-radius:8px; margin-top:8px; background:#fff; }
    details summary { cursor:pointer; color: var(--primary-color); margin-top:8px; }
    .saved { color: var(--success-color,#43a047); font-size:.85em; margin-left:8px; }
    .warn { color: var(--warning-color,#ffa600); font-size:.85em; }
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
        .catch(() => null);
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
      } catch (e) {
        this._error = e.message || String(e);
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
      if (this._error) html += `<div class="empty">Schulmanager: ${esc(this._error)}</div>`;
      else if (!this._data) html += `<div class="empty">Lade …</div>`;
      else if (!this._data.children.length) html += `<div class="empty">Keine Kinder gefunden.</div>`;
      else for (const c of this._data.children) html += this._childHtml(c);
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
      const chips = [];
      if (c.overdue) chips.push(`<span class="chip red">${c.overdue} überfällig</span>`);
      if (open.length) chips.push(`<span class="chip">${open.length} offen</span>`);
      if (c.payments_text) chips.push(`<span class="chip">💶 ${esc(c.payments_text)} zu zahlen</span>`);
      if (c.unread) chips.push(`<span class="chip">📬 ${c.unread} ungelesen</span>`);
      let body = "";
      if (tab === "aufgaben") body = this._taskList(open, "Keine offenen Aufgaben 🎉");
      else if (tab === "erledigt") body = this._taskList(done, "Noch nichts erledigt.");
      else body = this._itemList(c.items);
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
              <div class="main"><div class="t">${esc(t.icon)} ${esc(t.title)}${t.has_files ? " 📎" : ""}</div>
              ${sub ? `<div class="s">${esc(sub)}</div>` : ""}</div>${due}</div>`;
        })
        .join("");
    }

    _itemList(items) {
      if (!items.length) return `<div class="empty">Keine Mitteilungen.</div>`;
      return items
        .map(
          (i) => `<div class="row ${i.read ? "" : "unread"}" data-item="${esc(i.uid)}">
            <span class="ud ${i.read ? "read" : ""}"></span>
            <div class="main"><div class="t">${i.urgency === "hoch" ? "🔴 " : ""}${esc(i.title)}${i.files ? " 📎" : ""}</div>
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
      if (bind) bind(ov);
    }

    _sourceHtml(item, opts = {}) {
      if (!item) return "";
      const files = item.files || [];
      const pdf = files.find((f) => (f.content_type || "").includes("pdf") || f.name.toLowerCase().endsWith(".pdf"));
      const text = (item.body || "").trim();
      const fileText = (item.text || "").trim();
      return `<div class="src">
          <div class="lbl">${esc(item.kind_label)} · ${fmtDate(item.sent)}${item.sender ? " · " + esc(item.sender) : ""}</div>
          <h3>${esc(item.title)}</h3>
          ${item.summary ? `<div class="summary">🤖 ${esc(item.summary)}</div>` : ""}
          <div class="btns">
            ${files.map((f) => `<a class="btn" href="${esc(f.url)}" target="_blank" rel="noopener">📄 ${esc(f.name)}</a>`).join("")}
            ${pdf ? `<button class="btn" data-preview="${esc(pdf.url)}">👁 PDF hier anzeigen</button>` : ""}
            ${item.url ? `<a class="btn" href="${esc(item.url)}" target="_blank" rel="noopener">↗ Im Eltern-Portal</a>` : ""}
          </div>
          <div class="pv">${opts.preview && pdf ? `<iframe src="${esc(pdf.url)}" title="Vorschau"></iframe>` : ""}</div>
          ${text ? `<details ${opts.openText ? "open" : ""}><summary>Text der Mitteilung</summary><pre>${esc(text)}</pre></details>` : ""}
          ${fileText ? `<details><summary>Text aus der PDF</summary><pre>${esc(fileText)}</pre></details>` : ""}
        </div>`;
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
      this._showDialog(`${esc(t.icon)} ${esc(t.title)}${t.child_name ? ` <span class="sub">· ${esc(t.child_name)}</span>` : ""}`, body, (ov) => {
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
      const body = `
        ${this._sourceHtml(i, { openText: true })}
        <div class="sec"><div class="lbl">Aufgaben aus dieser Mitteilung</div>
          ${i.tasks.length ? this._taskList(i.tasks, "") : `<div class="sub">Keine – reine Information.</div>`}</div>
        <div class="btns">
          <button class="btn mark">${i.read ? "Als ungelesen markieren" : "Als gelesen markieren"}</button>
          <button class="btn re">🤖 Neu auswerten</button>
        </div>`;
      this._showDialog(`${i.urgency === "hoch" ? "🔴 " : ""}${esc(i.title)}`, body, (ov) => {
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

  if (!customElements.get("schulmanager-card")) {
    customElements.define("schulmanager-card", SchulmanagerCard);
    window.customCards = window.customCards || [];
    window.customCards.push({
      type: "schulmanager-card",
      name: "Schulmanager",
      description: "Aufgaben und Mitteilungen aus dem Eltern-Portal – klickbar mit Status, Kommentar und PDF.",
      preview: false,
    });
    console.info(`%c SCHULMANAGER-CARD %c ${VERSION} `, "background:#03a9f4;color:#fff", "");
  }
})();
