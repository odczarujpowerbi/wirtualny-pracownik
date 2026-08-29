"""
Tytuły zadań, które agent zakłada SAM SOBIE (eskalacja, kontynuacja, prośba o
feedback) — jedno miejsce z prefiksami i rozpoznawaniem takich zadań.

Po co osobny moduł: bez wspólnego rozpoznawania mechanizm zapętla się na
własnych zadaniach. Żywy przebieg: zadanie "Ustalenie źródła danych i zakresu
inwentaryzacji SharePoint" poszło na eskalację ("Wymaga decyzji: ..."), po jej
zamknięciu task_feedback_requester założył "Feedback: Wymaga decyzji: ...", a po
zamknięciu TEGO zadania — "Feedback: Feedback: Wymaga decyzji: ...". Trzecie
ogniwo trafiło do wykonania przez bota, bramka jakości je odrzuciła (nie da się
napisać rzetelnego feedbacku do artefaktu procesu) i zadanie wylądowało jako
eskalacja do człowieka.

Rozpoznawanie po prefiksie tytułu, bo kontrakt zadania z Projectly
(projectly_client._map_task) nie niesie informacji "kto to założył".
"""

PREFIX_ESKALACJA = "Wymaga decyzji:"
PREFIX_KONTYNUACJA = "Kontynuacja:"
PREFIX_FEEDBACK = "Feedback:"

AUTO_PREFIXES = (PREFIX_ESKALACJA, PREFIX_KONTYNUACJA, PREFIX_FEEDBACK)


def is_auto_generated_title(title):
    """True, gdy tytuł należy do zadania założonego przez sam mechanizm."""
    tekst = (title or "").strip().lower()
    return any(tekst.startswith(prefix.lower()) for prefix in AUTO_PREFIXES)


def derived_title(prefix, title):
    """Tytuł zadania pochodnego. Nie nakłada tego samego prefiksu drugi raz —
    "Feedback: Feedback: X" nic nie wnosi ponad "Feedback: X"."""
    tytul = (title or "").strip()
    if tytul.lower().startswith(prefix.lower()):
        return tytul
    return f"{prefix} {tytul}"
