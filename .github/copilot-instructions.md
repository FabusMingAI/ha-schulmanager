# Copilot instructions – Schulmanager (Home Assistant custom integration)

Schulmanager reads Eltern-Portal (eltern-portal.org) via the library `pyelternportal`, turns parent letters, messages, polls, exam dates, timetable and substitution plan into tasks, deadlines, sensors, a calendar and push notifications, and ships three dashboard cards.

## Layout

- `custom_components/schulmanager/`
  - `portal.py` – portal client (subclass of `pyelternportal.ElternPortalAPI`) and pure HTML parsers (`parse_timetable`, `parse_substitutions`). New portal sections: add a pure `parse_*` function plus a hook in `SchulPortal.async_fetch`; a failing section must only add an error, never abort the fetch.
  - `classes.py` – `concerns_class()`: does an appointment text concern the child's class (filters entries of other classes/grades).
  - `analyzer.py` – AI prompt (summaries in the configured languages) and rule-based fallback.
  - `manager.py` – storage, merge logic, tasks, reminders, digest, notifications, `child_events()` (calendar + agenda data).
  - `sensor.py`, `todo.py`, `calendar.py` – entities; entity names come from `translations/*.json` (`entity.<platform>.<key>.name`).
  - `websocket.py` – data for the cards (`schulmanager/data`, `/item`, `/task`, `/subscribe`).
  - `dashboard.py` – builds the "Schule" dashboard; never overwrite a dashboard the user edited by hand.
  - `www/schulmanager-card.js` – plain JavaScript, no build step, three custom elements (`schulmanager-card`, `schulmanager-termine`, `schulmanager-stundenplan`). Bump `VERSION` when you change it.
- `tests/test_schulmanager.py` – runs against a real Home Assistant test instance (`pytest-homeassistant-custom-component`). Use the demo portal or fake `PortalResult` objects; never real portal access.

## Rules for every change

1. **Tests:** add or extend tests in `tests/test_schulmanager.py`; `pip install -r requirements_test.txt && pytest -q` must pass.
2. **Documentation in both languages:** update **README.md (English) and README.de.md (German)** equally – features, cards, entities, actions, events, notes. Never update only one of them.
3. **CHANGELOG.md:** new entry on top, English and German (`English text. / Deutscher Text.`), and bump `version` in `manifest.json` accordingly.
4. **No personal data:** use only fictional names (Anna, Max, Erika), fictional schools (bspgym, demo) and fictional teachers in code, tests, docs and screenshots.
5. **User-facing texts** (cards, notifications, AI prompts) are German; config flow texts exist in `translations/en.json` and `translations/de.json` – keep both in sync.
6. **Robustness:** the portal HTML is unofficial and changes. Parsers must tolerate missing elements; an empty or unexpected page must never wipe data that is already stored.
7. Keep `pyelternportal` pinned to the version in `manifest.json` / `requirements_test.txt`.
8. **Commit messages in English.**
