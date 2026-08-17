"""
Loguje użycie skilli/skryptów i skutek (sukces/porażka/czas/koszt)
(SKRYPTY.md kategoria J). Wejście dla task_retro_auditor.py i
skill_improver_bot.py (PLAN-WDROZENIA.md sekcje 8, 16) — na razie
zapisuje tylko surowe dane, analiza to kolejny krok poza Fazą 0-2.
"""

from datetime import datetime, timezone

import state_store


def log_usage(task_id, skill_name, outcome, detail=""):
    """outcome: 'success' | 'failure'"""
    now = datetime.now(timezone.utc).isoformat()
    state_store.record_event(task_id, f"skill_usage:{skill_name}:{outcome}", detail, now)


if __name__ == "__main__":
    log_usage("PRJ-TEST", "pbip_validate", "success", "3 strony, brak błędów")
    print(state_store.get_events("PRJ-TEST"))
