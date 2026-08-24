"""
Agent-sędzia: ocenia, czy TREŚĆ (plan przed wykonaniem, albo wynik po
wykonaniu) faktycznie odpowiada na zadanie — nie "czy plik istnieje"
(bot_franek_funkcjonalny.py) ani "czy wygląda dobrze wizualnie"
(bot_oskar_wizja.py), tylko czy to jest merytorycznie to, o co proszono.

Użyty DWA razy z tego samego kodu (`judge()`):
- `agentic_worker.py` woła go wprost, PRZED wykonaniem (ocena planu) —
  zero zmarnowanego czasu/kosztu na wykonanie złego podejścia.
- `bot_gustaw_bramka.py` woła `review()` PO wykonaniu (ocena wyniku), jak
  pozostali walidatorzy bramki jakości.

Wzorzec JSON-werdyktu jak `bot_oskar_wizja.py`, ale bez obrazu — reuse
`task_thinker.ask_model()` (hierarchia Claude Code -> SDK -> Ollama) zamiast
bezpośredniego wywołania SDK, bo nie potrzeba bloku 'image'.

Fail-closed: brak treści / brak modelu / JSON nieparsowalny -> aligned=False.
Milczące "ok", gdy nie potrafimy ocenić, byłoby gorsze niż fałszywy alarm —
zadanie i tak trafia wtedy do eskalacji/poprawki, nie ginie po cichu.
"""

import json

import cost_estimator
import task_thinker
from bot_common import verdict

BOT = "content"
RELEVANT_TOOLS_DEFAULT = ["agentic_task"]


def _build_prompt(task, content, mode):
    kontekst = (
        f"Zadanie: {task.get('title', '')}\n"
        f"Cel: {task.get('expected_result', '')}\n"
        f"Kryteria akceptacji: {task.get('acceptance_criteria', '')}\n"
    )
    if mode == "plan":
        naglowek, pytanie = "Plan", (
            "Oceń PLAN poniżej — czy realnie adresuje to zadanie? Nie musi być "
            "idealny ani szczegółowy, ale nie może pomijać sedna zadania ani "
            "robić czegoś innego, niż o co proszono."
        )
    else:
        naglowek, pytanie = "Wynik", (
            "Oceń WYNIK poniżej — czy to jest merytorycznie odpowiedź na to "
            "zadanie, zgodna z kryteriami akceptacji? Nie oceniaj stylu ani "
            "długości, tylko czy to jest TO, o co proszono."
        )
    return (
        f"{kontekst}\n{pytanie}\n\n{naglowek}:\n{content[:6000]}\n\n"
        "Odpowiedz WYŁĄCZNIE obiektem JSON, bez komentarza:\n"
        '{"aligned": true|false, "reasoning": "<1-2 zdania>"}'
    )


def _parse_verdict(text):
    """Wyciąga {'aligned':..., 'reasoning':...} z odpowiedzi (nawet gdy model
    doda tekst wokół JSON) — wzorzec bot_oskar_wizja._parse_json_verdict.
    Zwraca None, gdy nie da się sparsować albo 'aligned' nie jest bool-em."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data.get("aligned"), bool):
        return None
    return {"aligned": data["aligned"], "reasoning": str(data.get("reasoning") or "").strip()}


def judge(task, content, mode="wynik"):
    """Ocenia zgodność `content` (plan albo wynik) z zadaniem. Zwraca
    {"aligned", "reasoning", "cost_usd", "source"}. Nigdy nie rzuca."""
    if not content or not content.strip():
        return {"aligned": False, "reasoning": "Brak treści do oceny.", "cost_usd": 0.0, "source": None}

    prompt = _build_prompt(task, content, mode)
    odpowiedz = task_thinker.ask_model(prompt, caller="bot_content_check.review")
    if not odpowiedz.get("available") or not odpowiedz.get("text"):
        return {"aligned": False, "reasoning": "Brak modelu — nie mogę ocenić zgodności.",
                "cost_usd": 0.0, "source": None}

    cost_usd = cost_estimator.estimate_call(
        odpowiedz.get("source") or "claude_code",
        input_chars=len(prompt), output_chars=len(odpowiedz["text"]))

    werdykt = _parse_verdict(odpowiedz["text"])
    if werdykt is None:
        return {"aligned": False, "reasoning": "Odpowiedź modelu nieparsowalna — nie mogę ocenić zgodności.",
                "cost_usd": cost_usd, "source": odpowiedz.get("source")}

    return {**werdykt, "cost_usd": cost_usd, "source": odpowiedz.get("source")}


def review(task, execution_result, config=None):
    """Wejście zgodne z resztą bramki jakości (bot_gustaw_bramka.py:REGISTRY).
    Pomija (skipped) zadania, których narzędzie nie jest na liście
    config.relevant_tools — ocena treści nie ma sensu np. dla walidacji PBIP."""
    config = config or {}
    relevant = [str(t).lower() for t in config.get("relevant_tools", RELEVANT_TOOLS_DEFAULT)]
    tool = (execution_result.get("tool") or "").lower()
    if tool not in relevant:
        return verdict(BOT, "skipped", 0.3, f"Narzędzie '{tool}' poza zakresem oceny treści.")

    ocena = judge(task, execution_result.get("acceptance_notes"), mode="wynik")
    if ocena["aligned"]:
        return verdict(BOT, "approved", 0.8, ocena["reasoning"])
    return verdict(BOT, "rejected", 0.8, ocena["reasoning"], concerns=[ocena["reasoning"]])
