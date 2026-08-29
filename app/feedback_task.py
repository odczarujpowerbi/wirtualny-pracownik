"""
Rozpoznawanie zadań, które SAME SĄ prośbą o feedback (zakładanych przez
task_feedback_requester). Wspólne dla obu stron, bo obie muszą je rozpoznawać
tak samo:

- task_feedback_requester nie może prosić o feedback DO prośby o feedback —
  inaczej po każdym domknięciu powstaje kolejny poziom zagnieżdżenia
  ("Feedback: Feedback: ..."), bez końca;
- runner_loop nie może wykonywać prośby o feedback jak zwykłej pracy — to
  pytanie do człowieka o przebieg zadania, a nie zadanie do zrobienia.

Żywy incydent 29.08.2026 (zadanie cmtab0y5w09d9x819ktki36wx): zadanie
"Feedback: Feedback: Odpowiedzi na maile od Oli" przeszło pełną ścieżkę
wykonania (klasyfikacja, myślenie, worker — 0,20 USD), model słusznie orzekł
"plan nie odpowiada zadaniu", i całość poszła na eskalację do człowieka.
Prefiks był podwójny, bo prośba o feedback wracała do kolejki jako praca.

Rozpoznanie jest CELOWO wąskie: łapie wyłącznie zadania założone przez ten
mechanizm (znacznik w opisie albo prefiks tytułu RAZEM z treścią pytania).
Sam prefiks "Feedback: " nie wystarcza — człowiek ma prawo tak zatytułować
własne, prawdziwe zadanie i takiego nie wolno ani pomijać, ani zamykać.
"""

from projectly_client import _load_config as _load_projectly_config

# Prefiks tytułu zakładanej prośby o feedback.
FEEDBACK_TITLE_PREFIX = "Feedback: "

# Znacznik maszynowy w opisie — jednoznaczny ślad "to założył mechanizm".
# Zadania sprzed jego wprowadzenia rozpoznajemy po prefiksie + treści pytania.
FEEDBACK_MARKER = "[auto:prosba-o-feedback]"

# Treść pytania. Jedno źródło prawdy: task_feedback_requester wysyła dokładnie
# to samo w komentarzu i w opisie zakładanego zadania, a rozpoznanie szuka
# poniższego fragmentu — bez duplikatu tekstu, który mógłby się rozjechać.
FEEDBACK_PYTANIE = (
    "👋 Krótki feedback do tego zadania: ile realnie zajęło (jeśli różni się "
    "od estymacji), co było trudne, i czy zostały jakieś zaległości/podzadania "
    "do zamknięcia osobno? Odpowiedz komentarzem tutaj."
)
FEEDBACK_PYTANIE_FRAGMENT = "ile realnie zajęło"

DOMYSLNY_PREFIKS_KONTA_AI = "AI - "


def opis_prosby_o_feedback():
    """Opis zakładanego zadania: pytanie + znacznik maszynowy."""
    return f"{FEEDBACK_PYTANIE}\n\n{FEEDBACK_MARKER}"


def czy_prosba_o_feedback(task):
    """Czy zadanie jest prośbą o feedback założoną przez ten mechanizm."""
    opis = str(task.get("description") or "")
    if FEEDBACK_MARKER in opis:
        return True
    tytul = str(task.get("title") or "")
    return tytul.startswith(FEEDBACK_TITLE_PREFIX) and FEEDBACK_PYTANIE_FRAGMENT in opis


def prefiks_konta_ai():
    """Prefiks nazwy kont botów z config/projectly.yaml (ai_account.name_prefix)
    — ten sam, po którym ProjectlyClient._is_ai_account odróżnia bota od
    człowieka. Nieczytelny config nie może wywrócić rozpoznania, więc wtedy
    zostaje wartość domyślna."""
    try:
        cfg = _load_projectly_config()
    except Exception:  # noqa: BLE001 — config nieczytelny nie może zablokować rozpoznania
        return DOMYSLNY_PREFIKS_KONTA_AI
    return (cfg.get("ai_account") or {}).get("name_prefix", DOMYSLNY_PREFIKS_KONTA_AI)


def czy_wykonane_przez_konto_ai(task, prefiks=None):
    """Czy zadanie było przypisane do konta AI (bota), a nie do człowieka."""
    prefiks = prefiks or prefiks_konta_ai()
    return str(task.get("assignee") or "").startswith(prefiks)
