# WebUntis compatibility and review decisions

Checked on 16 October 2026 against upstream
[`e8e072f5590355376fccdfbaea2f13e2539485f1`](https://github.com/JonasJoKuJonas/homeassistant-WebUntis/tree/e8e072f5590355376fccdfbaea2f13e2539485f1).
This is a source-code check, not a test with a real WebUntis account.

## Calendar options and JSON

The [calendar-event builder](https://github.com/JonasJoKuJonas/homeassistant-WebUntis/blob/e8e072f5590355376fccdfbaea2f13e2539485f1/custom_components/webuntis/__init__.py#L1065)
filters cancellations using `calendar_show_cancelled_lessons` and invokes
`get_lesson_json(lesson, True)` when `calendar_description` is `json`.
`calendar_show_room_change` only adds a title prefix; it does not gate room data
in JSON. Therefore JSON descriptions and showing cancelled lessons are required;
the room-change title prefix is optional. Other upstream filters can still remove
lessons before they reach the calendar.

The [calendar entity](https://github.com/JonasJoKuJonas/homeassistant-WebUntis/blob/e8e072f5590355376fccdfbaea2f13e2539485f1/custom_components/webuntis/calendar.py#L65)
returns overlapping events from the provider's stored snapshot. Our integration
reads it through HA's `calendar.get_events`, without handling WebUntis credentials.

## Missing teachers

[`get_lesson_json`](https://github.com/JonasJoKuJonas/homeassistant-WebUntis/blob/e8e072f5590355376fccdfbaea2f13e2539485f1/custom_components/webuntis/__init__.py#L1359)
only serializes current and original teachers when `teachers` is not excluded.
If resolving current teachers raises `no right for getTeachers()`, it adds
`teachers` to both the runtime exclusion and a pending exclusion list.
[`exclude_data_`](https://github.com/JonasJoKuJonas/homeassistant-WebUntis/blob/e8e072f5590355376fccdfbaea2f13e2539485f1/custom_components/webuntis/__init__.py#L1476)
persists the exclusion in the integration options.

However, the current
[`teachers()` implementation](https://github.com/JonasJoKuJonas/homeassistant-WebUntis/blob/e8e072f5590355376fccdfbaea2f13e2539485f1/custom_components/webuntis/utils/web_untis_extended.py#L335)
also has a timetable/REST teacher mapping fallback for forbidden `getTeachers()`.
It is therefore inaccurate to state that every account without that permission
necessarily loses all teacher data. Whether the fallback succeeds depends on
the actual backend, account and version. An existing persisted exclusion may
still prevent serialization.

Without teacher data, our parser cannot recognize teacher-only changes. It
continues to recognize explicit cancellations and room changes. Diagnostics
report a structured calendar that has not yet supplied a `teachers` list, and
remember when that field has been observed. An empty calendar alone is not
treated as proof of missing permissions. The warning does not identify the cause
as a confirmed permissions failure: explicit exclusion can produce the same data.

## Open product decision: irregular lessons

Upstream labels `code == "irregular"` in its calendar title and exposes the code
in JSON. Our parser still requires cancellation or an actual teacher/room change.
An irregular lesson without usable `original_*` data is ignored; if a move is
represented by an old cancellation plus such a new lesson, only the cancellation
is imported.

**Open for Fabian:** should these irregular lessons become an additional event
kind, and how should they be distinguished from substitutions, moved lessons and
ordinary timetable additions? No irregular-lesson behavior is implemented by this
review follow-up.

## Notification and timetable decisions

- Displays keep combining both original sources, including different spellings
  and notes. Notification grouping uses the child's local date, explicit start
  and end (portal timetable times when necessary), and change kind. Without known
  start/end times, cross-source grouping is deliberately not inferred from names.
- A slot first reported/observed in one source does not notify again just because
  another source first supplies it later. Each source's later real content changes
  can still notify. Source observations are stored across restarts. Simultaneous
  cross-source entries share a message line with distinct notes combined.
- WebUntis fingerprints exclude derived lesson numbers and identifiers. Older
  cache snapshots seed the new hashes without an upgrade notification flood.
- Period matching requires at least 50% overlap of a portal period. A double
  lesson must match consecutive, non-overlapping periods with more than 50%
  coverage of each; boundary ties or conflicting times remain unassigned.
  Explicit calendar start/end times are always retained.
- Calendar reads wait until HA has started. The portal fetch remains unchanged;
  the start callback reads only assigned calendars. Portal status text is preferred
  over the time of a calendar fetch, and room-change text includes the old room.

## Still requires a real account

Use a parent account if possible to check permissions, teacher fallback/exclusion,
actual JSON fields, calendar filters and refresh latency. Also compare actual
portal and WebUntis time slots and inspect moved/irregular lessons. Synthetic
tests and green CI do not establish those account-specific behaviors.
