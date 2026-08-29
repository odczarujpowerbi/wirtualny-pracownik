"""
Agent sterujący decyduje, czy duże/niejasne zadanie warto rozbić na proste
podzadania, które bot wykona bezbłędnie — żadna reguła w kodzie nie wymusza
podziału po typie/słowach zadania. Rozbicie tworzy PRAWDZIWE podzadania w
Projectly (Task.parentTaskId, nie TaskRelation z zbot_link_tasks — patrz
projectly_client.create_task, parametry subtask_of/order) i oznacza zadanie
główne statusem "przeniesione" — czwartym, natywnym statusem Projectly dla
kontenera rozbitego na podzadania (potwierdzone przez właściciela Projectly
24.08.2026, wdrożone na produkcję w commicie 261).

Rozdział odpowiedzialności jak output_decider.py: `decide()` pyta model i
waliduje odpowiedź, `decompose()` wykonuje decyzję (tworzy zadania, zamyka
rodzica) — model nigdy nie tworzy zadań sam, tylko proponuje ich treść.

Fail-closed: brak modelu / nieparsowalna odpowiedź / mniej niż MIN_SUBTASKS
sensownych podzadań -> should_split=False, zadanie idzie normalną ścieżką
(klasyfikacja/wykonanie), tak jak dziś — rozbicie nigdy nie jest wymuszone.
"""

import json

import agentic_worker
import cost_estimator
import task_thinker
from projectly_client import effective_priority

MIN_SUBTASKS = 2
MAX_SUBTASKS = 5

# Budżet czasu jednego subagenta — ta sama liczba, co twardy timeout procesu
# w agentic_worker.py (AGENTIC_TIMEOUT_SECONDS), żeby kryterium podziału nie
# rozjechało się z rzeczywistym limitem wykonania. Decyzja właściciela
# 24.08.2026: komputer się zawiesił po rozbiciu zadania na zbyt wiele
# podzadań wykonywanych jedno po drugim — dzielić TYLKO gdy realnie się nie
# zmieści w tym budżecie, nie z powodu samej liczby kroków.
TIME_BUDGET_MINUTES = agentic_worker.AGENTIC_TIMEOUT_SECONDS // 60

_ZDOLNOSCI_BOTA = (
    "- fetch_url: pobranie treści strony (GET, tylko odczyt)\n"
    "- browser_task: klikanie/wypełnianie formularza w przeglądarce\n"
    "- capture_screenshot / validate_pbip: zrzut ekranu / walidacja struktury PBIP\n"
    "- mailerlite_report / zanfia_query: zestawienie z MailerLite / Zanfia\n"
    "- proste zadanie analityczne albo tekstowe o WĄSKIM, jednoznacznym zakresie "
    "(bez tych narzędzi, ale z jasnym 'co' i 'jak sprawdzić czy zrobione')"
)


def _build_prompt(task):
    return (
        f"Zadanie: {task.get('title', '')}\n"
        f"Cel: {task.get('expected_result', '')}\n"
        f"Kryteria akceptacji: {task.get('acceptance_criteria', '')}\n"
        f"Opis: {(task.get('description') or '')[:2000]}\n\n"
        f"Dziś bot ma te zdolności:\n{_ZDOLNOSCI_BOTA}\n\n"
        "Zdecyduj: da się to wykonać JEDNYM ciągłym przebiegiem subagenta "
        f"(Read/Write/Edit, bez przerwy) w ~{TIME_BUDGET_MINUTES} minutach, czy "
        "realnie nie zmieści się w tym czasie? To jest JEDYNE kryterium podziału — "
        "nie liczba kroków ani to, że zadanie 'ma kilka części'. Najpierw oszacuj "
        "czas w minutach (estimated_minutes), potem z NIEGO wyprowadź split: "
        f"gdy estimated_minutes <= {TIME_BUDGET_MINUTES} -> split=false, nawet jeśli "
        "zadanie wygląda na wieloetapowe. Gdy split=true — rozbij na od "
        f"{MIN_SUBTASKS} do {MAX_SUBTASKS} podzadań, każde mapujące się na JEDNĄ "
        "zdolność z listy (albo wąski task tekstowy), z jednoznacznym tytułem i "
        "opisem (co zrobić, jak sprawdzić czy zrobione dobrze), każde SAMO w "
        f"budżecie ~{TIME_BUDGET_MINUTES} minut.\n\n"
        "Odpowiedz WYŁĄCZNIE obiektem JSON, bez komentarza:\n"
        '{"estimated_minutes": <liczba>, "split": true|false, "reasoning": "<1-2 zdania>", '
        '"subtasks": [{"title": "...", "description": "..."}]}'
    )


def _parse_decision(answer_text):
    """Wyciąga decyzję z odpowiedzi modelu (nawet gdy doda tekst wokół JSON) —
    wzorzec output_decider._parse_decision / bot_oskar_wizja._parse_json_verdict.
    Zwraca None, gdy nie da się sparsować, `split` nie jest bool-em, albo
    `subtasks` nie jest listą."""
    start, end = answer_text.find("{"), answer_text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(answer_text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data.get("split"), bool) or not isinstance(data.get("subtasks"), list):
        return None
    subtasks = [
        {"title": str(s.get("title") or "").strip(), "description": str(s.get("description") or "").strip()}
        for s in data["subtasks"] if isinstance(s, dict) and str(s.get("title") or "").strip()
    ]
    estimated_minutes = data.get("estimated_minutes")
    if not isinstance(estimated_minutes, (int, float)) or isinstance(estimated_minutes, bool):
        estimated_minutes = None
    return {"split": data["split"], "reasoning": str(data.get("reasoning") or "").strip(),
            "subtasks": subtasks, "estimated_minutes": estimated_minutes}


def decide(task):
    """Pyta model, czy rozbić zadanie na podzadania. Zwraca {"should_split",
    "reasoning", "subtasks", "cost_usd", "source"}. Nigdy nie rzuca — brak
    modelu / odpowiedź nie do sparsowania / za mało sensownych podzadań
    degradują do should_split=False, cost_usd=0.0 (poza kosztem realnego
    wywołania modelu, gdy ono nastąpiło)."""
    prompt = _build_prompt(task)
    odpowiedz = task_thinker.ask_model(prompt, caller="task_decomposer.decide")
    if not odpowiedz.get("available") or not odpowiedz.get("text"):
        return {"should_split": False, "reasoning": "Brak modelu — zadanie idzie normalną ścieżką.",
                "subtasks": [], "cost_usd": 0.0, "source": None}

    cost_usd = cost_estimator.estimate_call(
        odpowiedz.get("source") or "claude_code",
        input_chars=len(prompt), output_chars=len(odpowiedz["text"]))

    decyzja = _parse_decision(odpowiedz["text"])
    if decyzja is None or not decyzja["split"]:
        reason = "Odpowiedź modelu nieparsowalna — zadanie idzie normalną ścieżką." if decyzja is None \
            else (decyzja["reasoning"] or "Model uznał zadanie za wystarczająco proste.")
        return {"should_split": False, "reasoning": reason, "subtasks": [],
                "cost_usd": cost_usd, "source": odpowiedz.get("source")}

    # Model sam sobie zaprzeczył (chce dzielić, ale własny szacunek mieści się
    # w budżecie) — fail-closed w stronę NIE dzielenia, żeby liczba kroków
    # sama z siebie nie napędzała dekompozycji.
    est = decyzja["estimated_minutes"]
    if est is not None and est <= TIME_BUDGET_MINUTES:
        return {"should_split": False,
                "reasoning": f"Model oszacował {est} min (budżet {TIME_BUDGET_MINUTES} min), mimo to "
                             "chciał dzielić — sprzeczne, zadanie idzie normalną ścieżką.",
                "subtasks": [], "cost_usd": cost_usd, "source": odpowiedz.get("source")}

    subtasks = decyzja["subtasks"]
    if len(subtasks) < MIN_SUBTASKS:
        return {"should_split": False,
                "reasoning": f"Model chciał podzielić, ale zaproponował tylko {len(subtasks)} "
                             f"podzadanie/a (minimum {MIN_SUBTASKS}) — zadanie idzie normalną ścieżką.",
                "subtasks": [], "cost_usd": cost_usd, "source": odpowiedz.get("source")}
    if len(subtasks) > MAX_SUBTASKS:
        subtasks = subtasks[:MAX_SUBTASKS]

    return {"should_split": True, "reasoning": decyzja["reasoning"], "subtasks": subtasks,
            "cost_usd": cost_usd, "source": odpowiedz.get("source")}


def decompose(client, task, decyzja):
    """Wykonuje decyzję: tworzy podzadania jako PRAWDZIWE dzieci (subtask_of),
    w tym samym projekcie co rodzic. Zwraca {"created_ids", "comment"} — komentarz
    do wklejenia na zadaniu głównym, gotowy tekst z listą utworzonych podzadań."""
    project_id = task.get("project_id")
    # Podzadania dziedziczą priorytet rodzica (29.08.2026, decyzja właściciela)
    # — rodzic trafił do przetworzenia W TYM cyklu, więc jego priorytet był
    # (per runner_loop._wybierz_partie_wg_priorytetu) najwyższym obecnym w
    # kolejce; dzieci mają zostać na tym samym poziomie pilności, nie spaść na
    # domyślny. effective_priority(), NIE `task.get("priority") or ...` —
    # priority=0 (PARKING) jest falsy i zostałby błędnie podbity do BIEŻĄCE.
    priorytet = effective_priority(task)
    created = []
    for i, sub in enumerate(decyzja["subtasks"]):
        child_id = client.create_task(
            sub["title"], sub.get("description") or "", assigned_to="bot",
            subtask_of=task["task_id"], order=i, project_id=project_id,
            priority=priorytet,
        )
        created.append({"task_id": child_id, "title": sub["title"]})

    linie = [f"Zadanie rozbite na {len(created)} podzadań ({decyzja['reasoning']}):"]
    linie += [f"- {c['title']} ({c['task_id']})" for c in created]
    return {"created_ids": [c["task_id"] for c in created], "comment": "\n".join(linie)}


def sibling_tasks(client, task):
    """Inne podzadania tego samego zadania głównego (task["parent_task_id"]) —
    kontekst dla agenta wykonującego (decyzja właściciela 25.08.2026: subagenty
    mają wiedzieć, co robią pozostałe podzadania). Żadne API nie filtruje tego
    po stronie serwera — filtr po parent_task_id robimy tu, po liście zadań
    całego projektu. Fail-soft: brak project_id/parent_task_id albo błąd -> []."""
    parent_id = task.get("parent_task_id")
    if not parent_id or not task.get("project_id"):
        return []
    try:
        wszystkie = client.list_tasks(project_id=task["project_id"])
    except Exception:  # noqa: BLE001 — kontekst jest dodatkiem, nie warunkiem wykonania
        return []
    return [
        t for t in wszystkie
        if t.get("parent_task_id") == parent_id and t.get("task_id") != task.get("task_id")
    ]
