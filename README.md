# Schulmanager for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/FabusMingAI/ha-schulmanager/actions/workflows/validate.yml/badge.svg)](https://github.com/FabusMingAI/ha-schulmanager/actions/workflows/validate.yml)
[![Tests](https://github.com/FabusMingAI/ha-schulmanager/actions/workflows/tests.yml/badge.svg)](https://github.com/FabusMingAI/ha-schulmanager/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Deutsch:** [README.de.md](README.de.md)

Schulmanager turns the flood of school messages from **[Eltern-Portal](https://www.eltern-portal.org)** (used by many schools in Bavaria and other German states) into tasks, deadlines and reminders in Home Assistant – for all your children and schools in one place.

It signs in to the portal itself, stores parent letters and attachments per child, lets an AI read out what you actually have to do (sign, pay, return, bring along …) and reminds you in time.

![Dashboard](docs/images/dashboard.png)

## Features

- **Reads the portal directly** – parent letters (*Elternbriefe*), messages from teachers, notice board, surveys, exam dates, **timetable** and **substitution plan** (*Vertretungsplan*). Several schools and children with one installation.
- **Files per child** – PDFs and attachments go to `Media › schulmanager › <child> › <school year>`.
- **AI analysis** via Home Assistant's [AI Task](https://www.home-assistant.io/integrations/ai_task/) (Anthropic, OpenAI, Google, Ollama …): summary, urgency, tasks, deadlines, amounts, IBAN and payment reference, appointments. Without AI a simple rule-based detection is used.
- **Tasks with status** *open / in progress / done*, comments, due dates – as a to-do list, calendar and sensors.
- **Reminders** by push notification (with *Done* and *Remind me tomorrow* buttons), a daily morning summary and optional voice announcements.
- **Timetable & substitutions** – cancelled lessons, substitute teachers and room changes appear in the timetable card, the calendar (with lesson times) and the morning summary; a new change triggers a push notification.
- **Traffic light per child** – red / yellow / green for dashboards and automations.
- **Three dashboard cards included**, set up automatically in the "Schule" dashboard:
  - `custom:schulmanager-card` – tasks and messages; tap a task to see the letter, the PDF and the payment details.
  - `custom:schulmanager-termine` – appointments and deadlines of all children; hover an entry (tap on phones) to see the AI summary, with a legend of all category icons at the bottom.
  - `custom:schulmanager-stundenplan` – day and week timetable with full subject names; changes from the substitution plan are highlighted.

<p align="left"><img src="docs/images/task-dialog.png" width="260" alt="Task details"> <img src="docs/images/termine.png" width="260" alt="Appointments with AI summary on hover"> <img src="docs/images/stundenplan.png" width="260" alt="Timetable with substitutions"></p>

> The user interface texts of the card, notifications and the AI output are in German, because Eltern-Portal is a German service. Configuration dialogs are available in English and German.

## Requirements

- Home Assistant **2025.8** or newer (custom brand icon from 2026.3)
- An Eltern-Portal parent account (`https://<school>.eltern-portal.org`)
- Optional: an AI Task entity for the analysis

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/FabusMingAI/ha-schulmanager`, type **Integration**.
2. Search for **Schulmanager**, install, restart Home Assistant.

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=FabusMingAI&repository=ha-schulmanager&category=integration)

### Manual

Copy `custom_components/schulmanager` to `/config/custom_components/schulmanager` and restart Home Assistant.

## Setup

1. **Settings → Devices & services → Add integration → Schulmanager**
2. Enter the school code (the part before `.eltern-portal.org`) – or simply paste the link from a portal notification e-mail – plus e-mail and password. Add more schools in the same dialog.
3. **Configure → Settings**: choose the AI Task entity, the phones for push notifications (`notify.mobile_app_…`), reminder days and times, and optionally speakers or Assist satellites for announcements.
4. **Dashboard**: the integration creates the **"Schule"** dashboard in the sidebar by itself – tabs **Overview** (appointments & deadlines of all children, manual refresh) plus **one tab per child** (tasks & messages, timetable with substitutions, appointments), ideal on phones. Under **Configure → Settings → "Schule" dashboard** you can switch to *Single page* or *Do not manage*. Dashboards you change by hand are left alone (regenerate with the action `schulmanager.rebuild_dashboard`). The YAML in [`dashboard/`](dashboard/schulmanager_dashboard.yaml) is only an example for your own dashboards.

On the first run the last 120 days are imported; only the last 21 days (and all unconfirmed letters) are analysed and marked unread, older items go to the archive as read.

## Entities (per child)

| Entity | Description |
|---|---|
| `sensor.schule_<child>_status` | Traffic light `rot` / `gelb` / `gruen`; attributes contain open tasks and recent messages |
| `todo.schule_<child>_aufgaben` | Task list – complete, reschedule, add your own tasks |
| `calendar.schule_<child>_kalender` | Deadlines, appointments from letters, exam dates, substitutions and cancelled lessons |
| `sensor.schule_<child>_offene_zahlungen` | Open payments in € |
| `sensor.schule_<child>_nachste_frist`, `…_uberfallig`, `…_offene_aufgaben`, `…_ungelesene_mitteilungen` | Counters and next deadline |
| `sensor.schule_<child>_stundenplan` | Timetable: lessons today; day and week plan as attributes |
| `sensor.schule_<child>_vertretungen` | Substitution plan: changes from today (cancelled lessons, substitutes, room changes); new entries are pushed and shown in calendar and morning summary |
| `sensor.schulmanager_letzter_abruf` | Diagnostics: last update, errors, pending analyses |

Entity IDs follow your Home Assistant language (shown here for German).

## Actions

| Action | Purpose |
|---|---|
| `schulmanager.refresh` | Fetch all portals now |
| `schulmanager.mark_read` | Mark a message, a child or everything as read |
| `schulmanager.complete_task` / `schulmanager.update_task` | Change status, comment, due date or title |
| `schulmanager.add_task` | Add your own task |
| `schulmanager.reanalyze` | Let the AI analyse a message again |
| `schulmanager.send_digest` / `schulmanager.send_reminders` | Send summary or reminders now |
| `schulmanager.rebuild_dashboard` | Regenerate the "Schule" dashboard |
| `schulmanager.get_overview` | Returns everything as a response – e.g. for an Assist script "What's up at school?" |

Events for your own automations: `schulmanager_new_item`, `schulmanager_task_reminder` and `schulmanager_substitution` (new substitution plan entries, with `child` and `entries`).

## Good to know

- **Receipt confirmation:** Eltern-Portal counts downloading a parent letter as *receipt confirmed*. With automatic file storage enabled, Schulmanager therefore confirms new letters when it fetches the PDF. Turn off "Store attachments/PDFs automatically" if you do not want that – you then get a task "confirm receipt in the portal" instead.
- **Privacy:** everything stays in Home Assistant. If you select an AI service, the text and PDF content of a message is sent to that provider for analysis. File links in the dashboard are signed and expire after 30 days.
- **Cards in your own dashboards:** all three cards accept an optional `child: <name>`; without it they show all children.
- **Timetable and substitution plan** are only available if the school has enabled them in Eltern-Portal. If the portal briefly returns an empty page, the last known plan is kept.
- **Unofficial:** Eltern-Portal has no public API. Access uses the library [pyelternportal](https://github.com/michull/pyelternportal), which reads the web pages. If the portal layout changes, single sections may stop working until an update; the error shows up in `sensor.schulmanager_letzter_abruf`.
- This project is not affiliated with Eltern-Portal or its operator.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

Issues and pull requests are welcome.

## License

[MIT](LICENSE)
