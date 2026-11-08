# Integration quality: Bronze towards Gold

This is a self-assessment against the [Home Assistant rules](https://contributors.home-assistant.io/core/quality-scale/rules/), checked on 8 November 2026. It is **not an official tier**. This HACS integration remains Custom. The machine-readable checklist is in [quality_scale.yaml](../custom_components/eltern_portal_schulmanager/quality_scale.yaml); no metal tier is declared in the manifest.

## Current implementation and verification

- Actions are registered when the integration loads, stay registered after unloading an entry, and raise a translated validation error when no entry is loaded.
- UI setup validates each school before saving. Credentials can be changed using the entry menu → Reconfigure, without removing messages, tasks, settings or entity IDs. The school selector changes an existing school's credentials; add/remove schools under Configure instead.
- Authentication failure during polling starts Home Assistant's reauthentication flow. Repeated failures use the same active flow. Other schools continue to update.
- Connection/authentication failures retain stored data. Timetable, substitution and sick-note sensors become unavailable for the affected school until it responds again. Locally stored tasks, inbox counters, payment totals and the calendar remain usable from the last stored data; they are local records, not confirmation that the portal is reachable. A partial response is recorded separately; its successfully fetched sections still merge. Section-level freshness needs further work.
- Failures and recovery are logged once per school/status transition. The diagnostic timestamp records the last fetch attempt, including failed attempts, not necessarily the last successful fetch. The error attribute provides the current errors.
- Diagnostics can be downloaded from the integration entry's menu. The integration payload includes aggregate counts, fixed health categories, pending queue sizes and the last fetch time. It excludes credentials, entry data/options, school identifiers, names, messages, tasks, sick-note details, files, teacher lists, URLs, AI content and free-text errors. Home Assistant supplies its normal system metadata separately.
- Each school/attempt keeps its own cookie session and connection pool, explicitly closed after the attempt. A migration to Home Assistant-managed sessions is a separate Platinum audit: its helper supplies a shared connector, so passing the existing private connector is incompatible. This preserves separation between accounts and the retry behaviour that addresses stale portal connections.

CI runs all existing and new tests, saves coverage.json and coverage.xml as the integration-coverage artifact, and requires 100% line coverage of config_flow.py and diagnostics.py. It reports each module at or below 95% as an outstanding Silver requirement. A passing overall test suite or a high overall percentage does not establish Silver. No coverage exclusions are used to hide untested integration code.

## Verified baseline

GitHub Actions on implementation commit d360f0046bd7b50f2fb3cd96e3cb2eeb3d38c5dd: 89 Python tests passed (27 additional cases), plus passing HACS, hassfest and browser checks. The integration has 3,427 executable Python statements with 333 uncovered (about 90% overall). Configuration flow and diagnostics both have 100% line coverage. Nine modules are still at or below 95%; the most substantial gaps are in manager, portal, migration, analyzer and websocket behaviour. See the [test run](https://github.com/FabusMingAI/ha-schulmanager/actions/runs/42467913841) for the full report.

## Remaining milestones

1. Bronze: full flow coverage, review every baseline rule, and resolve the cached-start connectivity audit item before claiming all requirements are met.
2. Silver: more than 95% coverage **in every module**, plus complete error/action and availability review. Current measurements come from each CI run; the checklist deliberately keeps the overall coverage requirement open.
3. Gold: dynamic child entity creation and stale-device handling, translated action exceptions/icons, full diagnostic review and documentation review. Devices are logical services per child; unsupported discovery is exempt because a remote Eltern-Portal account cannot be discovered on the local network.
4. Platinum: strict typing, managed HTTP sessions and full asynchronous-dependency audit. It is not the current milestone.

## Installation parameters

| Field | Required | Meaning |
|---|---|---|
| School code or portal link | Yes | Existing Eltern-Portal school, e.g. demo; notification links are normalized to the school code. |
| E-mail | Yes | Parent account for this school. |
| Password | Yes | Password for that account; stored in Home Assistant's config entry. |

Multiple schools use separate credentials. The integration supports Eltern-Portal schools, not schulmanager-online.de. Timetables, substitutions, sick notes and course tables depend on which portal sections the school enables. There is no official API; HTML changes can break individual sections. AI extraction can make mistakes; check payment details and deadlines against the original letter. Sick notes are read only.

## Configuration parameters

Configure → Settings stores options independently of credentials. Times use Home Assistant's configured local time zone.

| Option | Default | Meaning |
|---|---|---|
| AI Task entity | None | No AI provider: use local rules. Selecting a provider sends message/PDF text to it. |
| Summary languages | German, English | Choose from German, English, Spanish and Catalan; empty selection restores the default. |
| Push services | None | Companion-app notification services. |
| Daily summary | Enabled | Sends a summary only if there is relevant content. |
| Summary time | 06:45 | Local time for daily summary. |
| Reminder time | 18:30 | Local time for due-date reminders. |
| Reminder days | 3,1,0 | Days before deadline; overdue tasks are reminded daily. |
| Voice targets | None | Assist satellites or media players; empty disables announcements. |
| TTS entity | None | Required for media-player announcements. |
| Voice window | 07:00–20:30 | Time window for announcements. |
| Poll interval | 30 minutes | UI range 10–360 minutes. Manual refresh also fetches the portal. |
| Store PDFs/attachments | Enabled | Downloading letters can confirm receipt in Eltern-Portal. |
| Initial analysis window | 21 days | UI range 0–365; older initial messages are stored as read. |
| Import lookback | 120 days | UI range 7–400; how far back messages are fetched. |
| Portal appointments | Exams and tests | School appointments can also be included. |
| Own class only | Enabled | Hide appointments explicitly limited to other classes. |
| Teacher display | Abbreviation and name | Alternatively names only or abbreviations only. Teacher directory is fetched at most daily. |
| Dashboard | Tabs | Overview plus a tab per child; alternatives single page or unmanaged. |

## Troubleshooting

- **Wrong password:** the integration offers reauthentication. Select the affected school and enter the current password. To change credentials proactively, use Reconfigure. A failed validation leaves the old credentials untouched.
- **Portal outage:** wait for the next regular fetch; the client retries one connection failure within a fetch. Do not remove the integration. Other schools and local tasks remain usable.
- **One section missing:** check whether the school enables it and inspect the last-update sensor's errors. Retained data can be older than the most recent fetch; a successful login alone does not prove every optional section was refreshed.
- **Report a bug:** attach the diagnostics download and describe the affected feature. Do not attach actual letters, account passwords or unredacted server logs. The counters deliberately omit school/child names; describe which section failed in your own words.

## Automation examples and use cases

Use the generated task list for completing/rescheduling school tasks and the calendar for deadlines and school appointments. For a daily overview, the built-in morning digest is usually sufficient. To send it from your own automation, use the supported action:

~~~yaml
alias: School summary at breakfast
triggers:
  - trigger: time
    at: "07:15:00"
actions:
  - action: eltern_portal_schulmanager.send_digest
~~~

Disable the built-in daily summary to avoid two scheduled summaries. Action and event parameters, entities, reminders and calendar exports are described in the [README](../README.md#actions). The integration does not add custom automation condition or trigger platforms; its emitted events can be consumed by Home Assistant's standard event trigger.

## Removal and retained files

Remove an individual school via Configure → Remove school. Its local messages/tasks are removed; downloaded media files remain. To remove the final school, delete the integration entry under Settings → Devices & services. Remove the repository in HACS and restart Home Assistant to uninstall its code. Downloaded documents under media/eltern_portal_schulmanager remain for you to retain or delete. Remove generated dashboards/cards and any automations referring to the integration if you no longer want them. Uninstalling does not change your account at the school or undo previously confirmed letter receipts.
