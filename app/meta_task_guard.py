"""
Rozpoznawanie zadań META, czyli takich, które agent sam założył w Projectly:
eskalacji ("Wymaga decyzji: ...") i próśb o feedback ("Feedback: ...") dla
człowieka oraz kontynuacji ("Kontynuacja: ...") dla siebie.

Po co to jest (żywy incydent 29.08.2026): eskalacja tworzona przez
escalation.escalate_to_human wracała do runnera w get_new_tasks — create_task z
pustym assigneeIds (gdy osoby z `escalation_default_assignee` nie ma w katalogu
Projectly) przypisuje zadanie wg uprawnień tokenu, czyli do konta AI, które je
utworzyło. Runner brał ją jak zwykłe zadanie, nie umiał "wykonać decyzji
człowieka", więc bramka jakości ją odrzucała i eskalował ją PONOWNIE. Tytuł
narastał z każdym cyklem:

    Zbierz dane o Looker Studio, Metabase i Superset (fetch_url)
    Wymaga decyzji: Zbierz dane...
    Wymaga decyzji: Wymaga decyzji: Zbierz dane...
    Wymaga decyzji: Feedback: Wymaga decyzji: Wymaga decyzji: Zbierz dane...

a człowiek dostawał kolejne kopie tego samego pytania. Dwa progi zamykają tę
pętlę: runner POMIJA zadania dla człowieka (is_for_human), a tytuły meta-zadań
są IDEMPOTENTNE (escalation_title/continuation_title zdejmują istniejące
przedrostki, zamiast doklejać kolejny).
"""

ESCALATION_PREFIX = "Wymaga decyzji:"
FEEDBACK_PREFIX = "Feedback:"
CONTINUATION_PREFIX = "Kontynuacja:"

# Zadania META należące do CZŁOWIEKA — agent ich nie wykonuje ani nie eskaluje
# dalej. Kontynuacji tu NIE MA: to zadanie dla agenta, z decyzją człowieka już
# wbudowaną w opis (escalation.continuation_task_creator).
FOR_HUMAN_PREFIXES = (ESCALATION_PREFIX, FEEDBACK_PREFIX)

_ALL_PREFIXES = FOR_HUMAN_PREFIXES + (CONTINUATION_PREFIX,)

SKIP_REASON = "Zadanie eskalacyjne (dla człowieka) - bot go nie dekomponuje/wykonuje."


def strip_meta_prefixes(title):
    """Zdejmuje WSZYSTKIE wiodące przedrostki meta, także powtórzone
    ("Wymaga decyzji: Feedback: X" -> "X"). Zwraca tytuł oryginalny, gdy po
    zdjęciu nic by nie zostało (tytuł złożony z samych przedrostków)."""
    original = (title or "").strip()
    text = original
    zmieniono = True
    while zmieniono:
        zmieniono = False
        for prefix in _ALL_PREFIXES:
            if text[: len(prefix)].lower() == prefix.lower():
                text = text[len(prefix):].strip()
                zmieniono = True
    return text or original


def escalation_title(title):
    """Tytuł zadania eskalacyjnego — idempotentny: eskalacja eskalacji daje ten
    sam tytuł, nie kolejny przedrostek."""
    return f"{ESCALATION_PREFIX} {strip_meta_prefixes(title)}"


def continuation_title(title):
    """Tytuł zadania kontynuacyjnego — idempotentny, jak escalation_title."""
    return f"{CONTINUATION_PREFIX} {strip_meta_prefixes(title)}"


def feedback_title(title):
    """Tytuł zadania z prośbą o feedback — idempotentny, jak escalation_title."""
    return f"{FEEDBACK_PREFIX} {strip_meta_prefixes(title)}"


def is_meta_task(task):
    """Czy zadanie zostało założone przez agenta (eskalacja/feedback/kontynuacja)."""
    return _ma_przedrostek(task, _ALL_PREFIXES)


def is_for_human(task):
    """Czy to zadanie META należące do człowieka (eskalacja albo prośba o
    feedback). Runner takich nie przetwarza — czekają na odpowiedź człowieka."""
    return _ma_przedrostek(task, FOR_HUMAN_PREFIXES)


def _ma_przedrostek(task, przedrostki):
    title = (task.get("title") or "").strip().lower()
    return any(title.startswith(p.lower()) for p in przedrostki)
