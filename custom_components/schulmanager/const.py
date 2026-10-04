"""Konstanten für den Schulmanager."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "schulmanager"
LOGGER = logging.getLogger(__package__)

PLATFORMS: Final = ["sensor", "todo", "calendar"]

STORAGE_VERSION: Final = 1

# --- Konfiguration (entry.data) ---
CONF_PORTALS: Final = "portals"
CONF_SCHOOL: Final = "school"
CONF_SCHOOL_NAME: Final = "school_name"

# --- Optionen (entry.options) ---
CONF_AI_ENTITY: Final = "ai_task_entity"
CONF_NOTIFY: Final = "notify_services"
CONF_TTS_TARGETS: Final = "tts_targets"
CONF_TTS_ENGINE: Final = "tts_engine"
CONF_TTS_START: Final = "tts_start"
CONF_TTS_END: Final = "tts_end"
CONF_DIGEST_ENABLED: Final = "digest_enabled"
CONF_DIGEST_TIME: Final = "digest_time"
CONF_REMINDER_TIME: Final = "reminder_time"
CONF_REMINDER_DAYS: Final = "reminder_days"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_AUTO_DOWNLOAD: Final = "auto_download"
CONF_LOOKBACK_DAYS: Final = "lookback_days"
CONF_ANALYZE_DAYS: Final = "analyze_days"
CONF_DASHBOARD: Final = "dashboard"
CONF_APPOINTMENT_KINDS: Final = "appointment_kinds"
CONF_OWN_CLASS_ONLY: Final = "own_class_only"
CONF_SUMMARY_LANGUAGES: Final = "summary_languages"

DEFAULT_DIGEST_ENABLED: Final = True
DEFAULT_DIGEST_TIME: Final = "06:45:00"
DEFAULT_REMINDER_TIME: Final = "18:30:00"
DEFAULT_REMINDER_DAYS: Final = "3,1,0"
DEFAULT_TTS_START: Final = "07:00:00"
DEFAULT_TTS_END: Final = "20:30:00"
DEFAULT_SCAN_INTERVAL: Final = 30  # Minuten
DEFAULT_AUTO_DOWNLOAD: Final = True
DEFAULT_LOOKBACK_DAYS: Final = 120
DEFAULT_ANALYZE_DAYS: Final = 21

# Termine aus dem Portal (Kalender „Termine“): Arten laut Legende im Portal
APPT_SCHOOL: Final = "schule"  # Termin der Schule (event-info)
APPT_EXAM: Final = "schulaufgabe"  # Schulaufgabe der Klasse (event-important)
APPT_TEST: Final = "test"  # Test / Kurzarbeit / kl. Leistungsnachweis / Stegreifaufgabe (event-warning)
APPOINTMENT_KINDS: Final = [APPT_EXAM, APPT_TEST, APPT_SCHOOL]
DEFAULT_APPOINTMENT_KINDS: Final = [APPT_EXAM, APPT_TEST]
DEFAULT_OWN_CLASS_ONLY: Final = True

# Sprachen der KI-Zusammenfassung (Reihenfolge = Reihenfolge der Reiter)
SUMMARY_LANGUAGES: Final = ["de", "en", "es", "ca"]
DEFAULT_SUMMARY_LANGUAGES: Final = ["de", "en"]
MAX_SUMMARY_LANGUAGES: Final = 4
LANGUAGE_NAMES: Final = {"de": "Deutsch", "en": "English", "es": "Español", "ca": "Català"}
LANGUAGE_PROMPT_NAMES: Final = {"de": "Deutsch", "en": "Englisch", "es": "Spanisch", "ca": "Katalanisch"}

# --- Datenmodell ---
KIND_LETTER: Final = "elternbrief"
KIND_MESSAGE: Final = "nachricht"
KIND_BLACKBOARD: Final = "schwarzes_brett"
KIND_POLL: Final = "umfrage"
KIND_MANUAL: Final = "manuell"

KIND_LABELS: Final = {
    KIND_LETTER: "Elternbrief",
    KIND_MESSAGE: "Nachricht Lehrkraft",
    KIND_BLACKBOARD: "Schwarzes Brett",
    KIND_POLL: "Umfrage",
    KIND_MANUAL: "Manuell",
}

TASK_TYPES: Final = [
    "aufgabe",
    "zahlung",
    "rueckmeldung",
    "unterschrift",
    "mitbringen",
    "termin",
    "lesen",
]
TASK_TYPE_ICONS: Final = {
    "aufgabe": "✅",
    "zahlung": "💶",
    "rueckmeldung": "↩️",
    "unterschrift": "✍️",
    "mitbringen": "🎒",
    "termin": "📅",
    "lesen": "📖",
}

TASK_TYPE_LABELS: Final = {
    "aufgabe": "Aufgabe",
    "zahlung": "Zahlung",
    "rueckmeldung": "Rückmeldung",
    "unterschrift": "Unterschrift",
    "mitbringen": "Mitbringen",
    "termin": "Termin",
    "lesen": "Lesen",
}

# Kategorien im Kalender / in der Terminliste (Icon, Legende)
EVENT_CATEGORIES: Final = {
    "schulaufgabe": ("📝", "Schulaufgabe"),
    "test": ("✏️", "Test / Kurzarbeit / Stegreifaufgabe"),
    "portal": ("🏫", "Termin der Schule"),
    "termin": ("📅", "Termin aus einer Mitteilung"),
    "entfall": ("❌", "Stunde entfällt"),
    "vertretung": ("🔁", "Vertretung / Änderung"),
    "raum": ("🚪", "Raumänderung"),
    "krank": ("🤒", "Krankmeldung"),
}
SUBSTITUTION_KINDS: Final = ("entfall", "vertretung", "raum")

STATUS_OPEN: Final = "offen"
STATUS_DONE: Final = "erledigt"
STATUS_PROGRESS: Final = "in_arbeit"
TASK_STATUSES: Final = [STATUS_OPEN, STATUS_PROGRESS, STATUS_DONE]
STATUS_LABELS: Final = {STATUS_OPEN: "Offen", STATUS_PROGRESS: "In Arbeit", STATUS_DONE: "Erledigt"}

AMPEL_GREEN: Final = "gruen"
AMPEL_YELLOW: Final = "gelb"
AMPEL_RED: Final = "rot"

# --- Events ---
EVENT_NEW_ITEM: Final = f"{DOMAIN}_new_item"
EVENT_TASK_REMINDER: Final = f"{DOMAIN}_task_reminder"
EVENT_SUBSTITUTION: Final = f"{DOMAIN}_substitution"
SIGNAL_UPDATED: Final = f"{DOMAIN}_updated"

# Aktionen der Companion-App-Benachrichtigungen
ACTION_PREFIX: Final = "SCHULMANAGER"
ACTION_DONE: Final = f"{ACTION_PREFIX}_DONE"
ACTION_SNOOZE: Final = f"{ACTION_PREFIX}_SNOOZE"
ACTION_READ: Final = f"{ACTION_PREFIX}_READ"

MEDIA_SUBDIR: Final = "schulmanager"
FILE_URL_BASE: Final = f"/api/{DOMAIN}/datei"
CARD_URL: Final = f"/{DOMAIN}_static/schulmanager-card.js"
LOCAL_CARD_FILE: Final = "schulmanager-card.js"
LOCAL_CARD_URL: Final = f"/local/{DOMAIN}/{LOCAL_CARD_FILE}"

# Dashboard „Schule“
DASHBOARD_URL: Final = "dashboard-schule"
DASHBOARD_TITLE: Final = "Schule"
DASHBOARD_ICON: Final = "mdi:school"
DASHBOARD_TABS: Final = "tabs"
DASHBOARD_SINGLE: Final = "single"
DASHBOARD_OFF: Final = "off"
DASHBOARD_MODES: Final = [DASHBOARD_TABS, DASHBOARD_SINGLE, DASHBOARD_OFF]
DEFAULT_DASHBOARD: Final = DASHBOARD_TABS
LOCAL_ICON_URL: Final = f"/local/{DOMAIN}/icon.png"
