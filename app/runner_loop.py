"""
Główna pętla: pobiera zadania, klasyfikuje ryzyko, rozdziela do właściciela,
uruchamia walidatory dla żółtych, sprawdza granice bounded red dla
czerwonych, eskaluje sporne/czerwone jako osobne zadania, publikuje status
na żywo, zapisuje stan i koszt (PLAN-WDROZENIA.md sekcje 1-4, 17, SKRYPTY.md
kategoria A). Sprawdza kill switch na starcie każdej iteracji.

Czego celowo brakuje (uczciwie): prawdziwych workerów (Power BI, CRM, Meta
Ads...). `execution_result` poniżej jest zaślepką reprezentującą "zadanie
odebrane, praca jeszcze niewykonana realnie" — wystarczającą, żeby
przetestować mechanikę klasyfikacji/walidacji/eskalacji, ale nie
zastępującą realnego workera z Fazy 3+.

Użycie:
    python runner_loop.py            # jeden przebieg, tryb mock
    python runner_loop.py --loop      # ciągła pętla (Ctrl+C żeby zatrzymać)
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import env_bootstrap  # wczytuje .env / secrets/.env (patrz .env.example, bootstrap_init_secrets.py); też _current_role()

import agentic_worker
import bot_gustaw_bramka
import control
import cost_tracker
import executor
import heartbeat
import kill_switch
import poprawka_materialu
import live_status_publisher
import output_decider
import risk_classifier
import risk_hint
import sharepoint_link
import skill_usage_logger
import state_store
import task_decomposer
import task_router
import task_thinker
import validator_prompt
from escalation import ESCALATION_TITLE_PREFIX, escalate_to_human
from projectly_client import effective_priority, get_client

HINT_TO_ACTION = {
    "green": "read_report",
    "yellow": "report_build",
    "red": "budget_change",
}

# Ile zadań przetwarzamy w JEDNYM przebiegu run_once. get_new_tasks() nie ma
# własnego limitu (Projectly zwraca wszystko ze statusem "todo") — bez tego
# capa duży zaległy backlog (np. po rozbiciu zadania na podzadania) trafiał w
# całości do jednej, sekwencyjnej pętli i mógł zajmować maszynę godzinami bez
# przerwy (żywy incydent 24.08.2026: ~50 zadań na raz). Reszta nie przepada —
# zostaje w Projectly ze statusem "todo" i czeka na kolejny poll (30s, patrz
# schedule.yaml), więc to naturalna kolejka, nie utrata zadań.
MAX_TASKS_PER_RUN = 5


def _wybierz_partie_wg_priorytetu(tasks):
    """Z całej pobranej kolejki wybiera TYLKO zadania z najwyższego OBECNEGO
    priorytetu (żądanie właściciela 29.08.2026: przy dużym backlogu jeden
    przebieg ma najpierw posortować, potem wziąć czubek — nie "pierwsze z
    brzegu"). Nadmiar tego samego, najwyższego poziomu (ponad MAX_TASKS_PER_RUN)
    I wszystkie niższe poziomy wracają do `deferred` — to samo naturalne
    "zaczeka na kolejny poll", co wcześniej robił sam cap liczbowy, tylko
    priorytet decyduje PIERWSZY, limit liczbowy dopiero potem."""
    if not tasks:
        return [], []
    najwyzszy = max(effective_priority(t) for t in tasks)
    czolo = [t for t in tasks if effective_priority(t) == najwyzszy]
    reszta = [t for t in tasks if effective_priority(t) != najwyzszy]
    return czolo[:MAX_TASKS_PER_RUN], czolo[MAX_TASKS_PER_RUN:] + reszta


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _slug(text, limit=60):
    slug = re.sub(r"[^\w\-]+", "_", text or "", flags=re.UNICODE).strip("_")
    return (slug[:limit] or "zadanie")


def _save_result_to_onedrive(task, status, comment, execution_result=None):
    """Zapisuje wynik KAŻDEGO przetworzonego zadania do OneDrive (folder
    ONEDRIVE_TASKS_ROOT z secrets/.env, jeden podfolder per zadanie) — decyzja
    właściciela 23.08.2026: to ma być ZAWSZE, nie tylko wtedy, gdy ktoś ręcznie
    uruchamia skrypt generujący dokument. Ten folder to lokalny mirror
    biblioteki SharePoint (config/sharepoint.yaml), więc OneDrive sam wypycha
    zapis do SharePoint — bez potrzeby Microsoft Graph (patrz sharepoint_client.py,
    dziś zablokowany brakiem uprawnienia Sites.ReadWrite.All).

    Jaki DOKŁADNIE plik powstaje (md/docx/pdf/xlsx) decyduje `output_decider.py`
    — Agent sterujący, per zadanie, na podstawie realnego wyniku — nie sztywna
    reguła w tym kodzie (decyzja właściciela 24.08.2026: żadne "źródło X ->
    format Y"). Jeden plik `wynik_<task_id>.<format>` per zadanie.

    Podzadanie (task["parent_task_id"] ustawione, patrz task_decomposer.py)
    NIE dostaje własnego folderu — pisze do folderu RODZICA, wyszukanego po
    prefiksie task_id w nazwie (task_id jest zawsze pierwszym segmentem, patrz
    niżej) — bez potrzeby znać tytułu rodzica czy trzymać osobne mapowanie na
    dysku; źródłem prawdy o hierarchii jest samo Projectly (parentTaskId).

    Fail-soft: brak ONEDRIVE_TASKS_ROOT albo błąd zapisu (w tym błąd wywołania
    modelu) NIE MOŻE zablokować przetwarzania zadania — to dodatkowy ślad, nie
    krytyczny krok pipeline'u. Zwraca ścieżkę folderu albo None, gdy nie zapisano.

    Nazwa folderu: PEŁNE task_id na początku (decyzja właściciela 23.08.2026 —
    id jako przedrostek, żeby zadanie było łatwe do wyszukania po id), potem
    data i skrócony tytuł dla człowieka. task_id jest zawsze dostępne — to
    surowe id z Projectly (`raw.get("id")` w projectly_client._map_task),
    ten sam identyfikator używany w całym pipeline, żadna zmiana MCP niepotrzebna."""
    root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    if not root:
        return None
    try:
        root_path = Path(root)
        if not root_path.parent.exists():
            return None  # OneDrive nie zsynchronizowany na tej maszynie — nie twórz sierocego folderu
        effective_id = task.get("parent_task_id") or task["task_id"]
        istniejace = sorted(root_path.glob(f"{effective_id}_*")) if root_path.exists() else []
        if istniejace:
            folder = istniejace[0]
        else:
            # Rodzic bez własnego folderu jeszcze (normalny przypadek) albo
            # podzadanie przetworzone PRZED rodzicem (rzadki wyścig) — w obu
            # razach tworzymy folder pod effective_id, samo-naprawiający się
            # brak blokady, nie wymaga specjalnej obsługi.
            data = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            folder = root_path / f"{effective_id}_{data}_{_slug(task.get('title', ''))}"
        acceptance_notes = (execution_result or {}).get("acceptance_notes") or comment
        table_rows = (execution_result or {}).get("table_rows")
        decision = output_decider.decide(task, status, comment, execution_result)
        if decision["cost_usd"]:
            cost_tracker.record_cost(task["task_id"], decision["cost_usd"])
        output_decider.build_file(task, decision, acceptance_notes, table_rows, folder)
        return str(folder)
    except Exception:  # noqa: BLE001 — zapis dodatkowy, błąd nie może ubić przetwarzania zadania
        return None


def process_task(task, policy, routing, client):
    """Przetwarza zadanie i oznacza DOMKNIĘCIE BLOKU (block_closed) przy statusie
    końcowym — to granica bezpiecznego resetu kontekstu: brief kolejnych zadań nie
    wciąga zamkniętego (task_brief_builder). Audyt zostaje, kontekst przestaje ciągnąć."""
    result = _process_task_core(task, policy, routing, client)
    if result and result.get("status") in ("done", "needs_approval", "przeniesione"):
        state_store.record_event(result["task_id"], "block_closed", result["status"], now_iso())
    return result


# Jeśli to samo task_id wróci z get_new_tasks() z lokalnym statusem końcowym
# sprzed mniej niż tylu minut — nie wykonuj drugi raz (żywy incydent
# 24.08.2026: to samo zadanie wykonane i skomentowane DWA razy w ~65s, bo
# update_status() do Projectly nie zdążył/nie doszedł, zanim kolejny poll
# 30s później znów zobaczył zadanie jako "todo"). Okno celowo krótkie — to ma
# łapać wyścig z pollingiem, nie blokować świadome, ludzkie przywrócenie
# zadania do ponownego wykonania dużo później.
DUPLICATE_GUARD_MINUTES = 15


def _process_task_core(task, policy, routing, client):
    task_id = task["task_id"]
    now = now_iso()

    # Zadanie utworzone przez escalate_to_human (tytuł "Wymaga decyzji: ...")
    # jest ZAWSZE dla człowieka — bot nigdy nie ma go dekomponować/wykonywać/
    # eskalować dalej. Żywy bug 25-26.08.2026: takie zadania czasem trafiały z
    # powrotem do kolejki bota (przypisanie po stronie Projectly nie zawsze
    # trafiało do człowieka) i były przetwarzane jak zwykłe nowe zadanie, co
    # mnożyło prefiks w kółko ("Wymaga decyzji: Wymaga decyzji: ..."), tworząc
    # kolejne podzadania i kolejne eskalacje bez końca. Krótkie cięcie: bez
    # względu na to, DLACZEGO bot to zobaczył, nigdy nie przetwarza dalej —
    # tylko potwierdza status "needs_approval" i kończy.
    if task["title"].startswith(ESCALATION_TITLE_PREFIX):
        state_store.upsert_task(task_id, payload=task, status="needs_approval", now=now)
        state_store.record_event(
            task_id, "escalation_task_skipped",
            "Zadanie eskalacyjne (dla człowieka) - bot go nie dekomponuje/wykonuje.", now)
        return {"task_id": task_id, "risk": None, "status": "needs_approval", "escalation_skip": True}

    existing = state_store.get_task(task_id)
    if existing and existing["status"] in ("done", "needs_approval", "przeniesione"):
        wiek = datetime.now(timezone.utc) - datetime.fromisoformat(existing["updated_at"])
        if wiek < timedelta(minutes=DUPLICATE_GUARD_MINUTES):
            state_store.record_event(task_id, "duplicate_skip", existing["status"], now)
            return {"task_id": task_id, "risk": existing.get("risk_level"),
                    "status": existing["status"], "duplicate": True}

    state_store.upsert_task(task_id, payload=task, status="planning", now=now)
    state_store.record_event(task_id, "task_received", task["title"], now)

    # Widoczność "co jest w trakcie" (żądanie właściciela 29.08.2026): zadanie,
    # które weszło do partii tego przebiegu (patrz _wybierz_partie_wg_priorytetu),
    # dostaje status "w trakcie" w REALNYM Projectly zanim zacznie się realna
    # praca — użytkownik ma widzieć na pierwszy rzut oka, co bot faktycznie
    # ciągnie teraz, a co dopiero czeka w kolejce (queued_tasks, live_status_publisher).
    # Fail-soft: to widoczność, nie krok pipeline'u — błąd MCP/sieci nie może
    # zablokować przetwarzania samego zadania.
    try:
        client.update_status(task_id, "in_progress")
    except Exception as exc:  # noqa: BLE001 — status wczesny to dodatek, nie krytyczny krok
        state_store.record_event(task_id, "early_status_update_failed", str(exc), now_iso())

    # Sprawdzenie bezpieczeństwa treści PRZED klasyfikacją ryzyka — wykryta
    # próba wstrzyknięcia eskaluje zawsze, niezależnie od koloru zadania
    # (dokumentacja bazowa 9.4: tekst zewnętrzny to dane, nie polecenie).
    prompt_check = validator_prompt.check_prompt_safety(task.get("title", ""))
    state_store.record_event(task_id, "prompt_safety_check", str(prompt_check), now_iso())
    if not prompt_check["safe"]:
        owner, _ = task_router.route_task(task["title"], routing)
        escalate_to_human(task, f"Wykryto podejrzaną treść: {prompt_check['detail']}", client)
        state_store.log_decision(
            task_id, agent="pawel", decision="escalate",
            reason=f"prompt injection: {prompt_check['detail']}", now=now_iso(), event_type="escalation")
        status = "needs_approval"
        state_store.upsert_task(task_id, payload=task, status=status, assigned_to=owner, risk_level="red", now=now_iso())
        komentarz = _comment_escalated(owner, prompt_check["detail"])
        client.post_comment(task_id, komentarz)
        client.update_status(task_id, status)
        _save_result_to_onedrive(task, status, komentarz)
        return {"task_id": task_id, "risk": "red", "owner": owner, "status": status}

    # Agent sterujący decyduje, czy to zadanie jest za duże/niejasne, żeby
    # wykonać je wprost — TYLKO dla zadań bez rozpoznanego, gotowego workera
    # (fetch_url/browser_task/mailerlite_report/... już same są "proste"),
    # które NIE są już podzadaniem (bez fraktalnej dekompozycji) i które nie
    # zostały już rozbite wcześniej (subtask_count>0 — redundancja z filtrem
    # statusu "przeniesione" w pollingu, na wypadek gdyby update_status zawiódł
    # po utworzeniu dzieci). Decyzja właściciela 24.08.2026, task_decomposer.py.
    already_subtask = bool(task.get("parent_task_id"))
    already_split = (task.get("subtask_count") or 0) > 0
    if already_subtask:
        # Kontekst rodzeństwa (inne podzadania tego samego zadania głównego) —
        # dostępny i dla task_thinker.think() (przez task_brief_builder, który
        # czyta dowolne pole z `task`), i dla agentic_worker.run() poniżej.
        # sibling_tasks() jest fail-soft samo w sobie (błąd/brak -> []).
        task["sibling_tasks"] = task_decomposer.sibling_tasks(client, task)
    if not already_subtask and not already_split and executor.rozpoznaj_narzedzie(task) is None:
        decyzja = task_decomposer.decide(task)
        if decyzja["cost_usd"]:
            cost_tracker.record_cost(task_id, decyzja["cost_usd"])
        state_store.log_decision(
            task_id, agent="pawel", decision=f"split={decyzja['should_split']}",
            reason=decyzja["reasoning"], now=now_iso(), event_type="decomposition")
        if decyzja["should_split"]:
            owner, _ = task_router.route_task(task["title"], routing)
            wynik = task_decomposer.decompose(client, task, decyzja)
            status = "przeniesione"
            state_store.upsert_task(task_id, payload=task, status=status,
                                    assigned_to=owner, risk_level="green", now=now_iso())
            client.post_comment(task_id, wynik["comment"])
            client.update_status(task_id, status)
            _save_result_to_onedrive(task, status, wynik["comment"])
            return {"task_id": task_id, "risk": "green", "owner": owner, "status": status}

    # Hint ryzyka: gdy źródło nie niesie własnego (albo niesie sztywny domyślny
    # 'yellow' z mapowania Projectly), wywnioskuj kolor Z TREŚCI zadania —
    # inaczej akcje czerwone (wysyłka/budżet/publikacja) nie byłyby rozpoznane.
    hint = task.get("risk_level_hint")
    if not hint or hint == "yellow":
        # Rozpoznanie workera PRZED klasyfikacją: gdy zadanie obsłuży narzędzie
        # czysto odczytowe, kolor bierze się z tej wiedzy, a nie ze słów w tytule
        # ("zestawienie WYSYŁEK KAMPANII" to odczyt, choć brzmi jak wysyłka).
        hint = risk_hint.hint_from_task(task, executor.rozpoznaj_narzedzie(task))
    action_type = HINT_TO_ACTION.get(hint, "report_build")
    risk = risk_classifier.classify(action_type, policy)
    owner, confident = task_router.route_task(task["title"], routing)

    state_store.log_decision(
        task_id, agent="pawel", decision=f"risk={risk}",
        reason=f"action_type={action_type}, właściciel={owner}, pewność routingu={confident}",
        now=now, event_type="classified",
    )

    # Krok myślenia: model analizuje zadanie (Claude Code headless przez
    # `claude login`, albo SDK z ANTHROPIC_API_KEY jako fallback). Degraduje się
    # bez wywalania pętli, gdy model niedostępny (task_thinker.think).
    # action_type trafia do zadania — task_brief_builder go czyta przy budowaniu
    # briefu dla kroku myślenia.
    task["action_type"] = action_type

    thinking = task_thinker.think(task)
    state_store.record_event(task_id, "thinking", thinking.get("detail", ""), now_iso())

    # Realny worker, jeśli istnieje dla tego typu zadania (dziś: walidacja PBIP,
    # fetch_url, browser_task, MailerLite/Zanfia...). Gdy None i mamy plan —
    # prawdziwy subagent (agentic_worker.py) wykonuje zadanie NAPRAWDĘ, zamiast
    # oddawać sam plan jako "wynik" (decyzja właściciela 24.08.2026: user ma
    # dostawać rezultat, nie instrukcję jak go zrobić). Brak modelu w ogóle —
    # zostaje dotychczasowa ścieżka "sama klasyfikacja", nic nie udajemy.
    real = executor.execute(task)
    if real is not None:
        execution_result = {**real, "thinking": thinking,
                            "cost_usd": real.get("cost_usd", 0.0) + thinking.get("cost_usd", 0.0)}
        state_store.log_decision(
            task_id, agent="patrycja", decision=real["tool"],
            reason=real["acceptance_notes"], now=now_iso(),
            event_type="execution", cost_usd=real.get("cost_usd", 0.0),
        )
    elif thinking.get("ok"):
        agentic = agentic_worker.run(task, thinking, client)
        execution_result = {**agentic, "thinking": thinking,
                            "cost_usd": agentic.get("cost_usd", 0.0) + thinking.get("cost_usd", 0.0)}
        state_store.log_decision(
            task_id, agent="patrycja", decision=agentic["tool"],
            reason=agentic["acceptance_notes"], now=now_iso(),
            event_type="execution", cost_usd=agentic.get("cost_usd", 0.0),
        )
    else:
        execution_result = {
            "cost_usd": thinking.get("cost_usd", 0.0),
            "acceptance_notes": thinking.get("reasoning") or "Brak modelu — sama klasyfikacja/routing.",
            "thinking": thinking,
        }
    cost_tracker.record_cost(task_id, execution_result["cost_usd"])

    # Worker/subagent odmówił wykonania (np. ścieżka poza dozwolonym katalogiem
    # roboczym, plan niedopasowany do zadania) — to zdarzenie bezpieczeństwa,
    # eskalujemy wprost, nie przez bramkę jakości (nie podajemy podejrzanej
    # treści dalej do botów). Sprawdzamy execution_result, NIE real — odmowa
    # subagenta nie ustawia `real` (executor.execute() zwrócił None).
    if execution_result.get("executed") is False:
        reason = execution_result["acceptance_notes"]
        escalate_to_human(task, reason, client)
        state_store.log_decision(task_id, agent="pawel", decision="escalate", reason=reason,
                                 now=now_iso(), event_type="escalation")
        state_store.upsert_task(task_id, payload=task, status="needs_approval",
                                assigned_to=owner, risk_level=risk, now=now_iso())
        komentarz = _comment_escalated(owner, reason)
        client.post_comment(task_id, komentarz)
        client.update_status(task_id, "needs_approval")
        _save_result_to_onedrive(task, "needs_approval", komentarz, execution_result)
        return {"task_id": task_id, "risk": risk, "owner": owner, "status": "needs_approval"}

    if already_subtask:
        # Decyzja właściciela 25.08.2026: podzadania z dekompozycji są z natury
        # słabo opisane (jednoznaczny, wąski krok, nie samodzielne zadanie) —
        # ocena bramki jakości/klasyfikacji ryzyka na gołej treści im nie
        # służy. Wykonują się zawsze automatycznie — bramka ORAZ eskalacja
        # czerwonego ryzyka pominięte z zasady. Zastrzeżenie: to bezpieczne
        # tylko dopóki agentic_worker/executor nie mają narzędzia mogącego
        # wykonać nieodwracalną akcję (dziś: brak Bash, brak API wysyłki/reklam) —
        # rewizja wymagana, jeśli taki tool kiedyś powstanie.
        state_store.log_decision(task_id, agent="pawel", decision="subtask_auto_done",
                                 reason="Podzadanie — bramka i ryzyko pominięte z zasady.",
                                 now=now_iso(), event_type="quality_gate")
        status, comment = "done", _comment_subtask_done(owner, execution_result)

    elif risk == "red":
        reason = "Czerwona akcja — poza zakresem tego szkieletu, brak jeszcze zdefiniowanej bounded_red do sprawdzenia."
        escalate_to_human(task, reason, client)
        state_store.log_decision(task_id, agent="pawel", decision="escalate", reason=reason,
                                 now=now_iso(), event_type="escalation")
        status, comment = "needs_approval", _comment_escalated(owner, reason)

    elif risk == "green" and not _has_effect(execution_result):
        # Zielone bez realnego efektu (np. sam odczyt) — szybka ścieżka, bez bramki.
        state_store.log_decision(task_id, agent="pawel", decision="auto_done",
                                 reason="zielone bez efektu — auto, bez bramki", now=now_iso())
        status, comment = "done", _comment_green(owner)
        skill_usage_logger.log_usage(task_id, "risk_classifier", "success", "zielone bez efektu, auto")

    else:
        # Żółte ORAZ zielone z efektem (zrzut/plik/testy) przechodzą pełną bramkę
        # jakości (Gustaw): Bartek, Franek, Oskar — zanim człowiek dostanie
        # odpowiedź jako gotową.
        gate = bot_gustaw_bramka.run_gate(task, execution_result)
        state_store.log_decision(
            task_id, agent="gustaw",
            decision="gate_passed" if gate["passed"] else "gate_failed",
            reason=gate["summary"], now=now_iso(), event_type="quality_gate")
        # Zanim cokolwiek trafi do człowieka: nanieś uwagi samodzielnie. Zastrzeżenia
        # bramki są konkretne ("brak jednostki", "miały być trzy zdania"), więc
        # odsyłanie ich właścicielowi to przerzucanie na niego pracy agenta.
        if not gate["passed"]:
            gate, execution_result = _popraw_i_sprawdz_ponownie(task, execution_result, gate)

        if gate["passed"]:
            status, comment = "done", _comment_gate_passed(owner, gate, execution_result)
            skill_usage_logger.log_usage(task_id, "quality_gate", "success", gate["summary"])
        elif _zadanie_zle_postawione(execution_result, gate):
            # Zadanie bez potrzebnych danych albo źle postawione. Zakładanie zadania
            # "wymaga decyzji" nic tu nie wnosi — zamykamy z konkretnym feedbackiem,
            # czego zabrakło, żeby właściciel mógł poprawić polecenie i wrzucić je
            # jeszcze raz. Agent ma zdejmować pracę, nie dokładać jej.
            reason = _gate_failure_reason(gate)
            state_store.log_decision(task_id, agent="pawel", decision="zamkniete_z_feedbackiem",
                                     reason=reason, now=now_iso(), event_type="escalation")
            status, comment = "done", _comment_zamkniete_z_feedbackiem(owner, execution_result, gate)
            skill_usage_logger.log_usage(task_id, "quality_gate", "failure", reason)
        else:
            reason = _gate_failure_reason(gate)
            escalate_to_human(task, reason, client)
            state_store.log_decision(task_id, agent="pawel", decision="escalate", reason=reason,
                                     now=now_iso(), event_type="escalation")
            status, comment = "needs_approval", _comment_escalated(owner, reason)
            skill_usage_logger.log_usage(task_id, "quality_gate", "failure", reason)

    state_store.upsert_task(task_id, payload=task, status=status, assigned_to=owner, risk_level=risk, now=now_iso())
    state_store.record_event(task_id, "status_set", status, now_iso())

    # Pochodzenie danych: metadane komentarza, nie część dostarczonego materiału.
    source_note = execution_result.get("source_note")
    if source_note:
        comment += "\n\n📎 Źródło: " + source_note

    reasoning = execution_result.get("thinking", {}).get("reasoning")
    if reasoning:
        comment += "\n\n🧠 Analiza (Claude):\n" + reasoning

    # Zapis do OneDrive PRZED komentarzem (kolejność zmieniona 29.08.2026,
    # decyzja właściciela: chce od razu, wchodząc w zadanie, mieć klikalny link
    # do folderu z materiałami — bez tego trzeba było szukać folderu ręcznie po
    # task_id). Plik w folderze budowany jest z `comment` SPRZED doklejenia tego
    # linku (nie ma sensu, żeby plik linkował do samego siebie).
    folder = _save_result_to_onedrive(task, status, comment, execution_result)
    link = sharepoint_link.folder_url(folder)
    if link:
        comment += f"\n\n📁 Materiały: {link}"

    client.post_comment(task_id, comment)
    client.update_status(task_id, status)
    _zapisz_feedback(client, task_id, status, execution_result, risk)

    return {"task_id": task_id, "risk": risk, "owner": owner, "status": status}


def _zapisz_feedback(client, task_id, status, execution_result, risk):
    """Samoocena agenta w polu `feedback` zadania (MCP update_task) — po to, żeby
    człowiek widział W ZADANIU, czym się skończyła praca, bez czytania całego
    wątku komentarzy. Zapisujemy zwięźle: co użyto, ile kosztowało, jaki wynik.

    Feedback to pole informacyjne, więc jego brak nie może wywrócić przebiegu —
    klient bez tej metody (starszy mock) albo błąd MCP są łapane."""
    zapis = getattr(client, "set_task_feedback", None)
    if not callable(zapis):
        return False

    narzedzie = execution_result.get("tool") or "brak workera"
    koszt = execution_result.get("cost_usd", 0.0)
    opis = {
        "done": "Wykonane i przyjęte przez bramkę jakości.",
        "needs_approval": "Wykonane, ale bramka jakości nie przepuściła — czeka na decyzję człowieka.",
    }.get(status, f"Status: {status}.")
    tresc = f"[agent] {opis} Narzędzie: {narzedzie}. Ryzyko: {risk}. Koszt modelu: {koszt:.2f} USD."
    try:
        # cost_usd (29.08.2026, docs/MCP-STATUS-I-KOSZTY.md): rozbicie kosztów
        # PER ZADANIE w Projectly (nie tylko dzienna suma z cost_tracker), żeby
        # master widział koszt każdego agenta jako sumę jego zadań.
        zapis(task_id, feedback=tresc, cost_usd=koszt)
        return True
    except Exception as exc:  # noqa: BLE001 — feedback jest dodatkiem, nie może ubić przebiegu
        state_store.log_decision(task_id, agent="pawel", decision="feedback_failed",
                                 reason=f"Nie udało się zapisać feedbacku: {exc}", now=now_iso())
        return False


def _has_effect(execution_result):
    """Czy zadanie wytworzyło realny efekt do walidacji (zrzut, plik, testy,
    powtarzalny przebieg). Zielone bez efektu idą szybką ścieżką, z efektem —
    przez bramkę (decyzja usera: żółte i wyżej + zielone z efektem)."""
    return any(execution_result.get(k) for k in ("screenshot_path", "output_file", "functional_checks", "rerun"))


def _comment_green(owner):
    return f"✅ done\nCo zrobiono: klasyfikacja i routing (Faza 0-1 — bez realnego workera jeszcze).\nPrzypisano do: {owner}\n"


def _comment_gate_passed(owner, gate, execution_result=None):
    """execution_result['acceptance_notes'] to RZECZYWISTY wynik workera (np.
    treść odpowiedzi fetch_url, opis tego co zobaczył browser_task) — bez tego
    komentarz mówił tylko 'bramka przeszła', a człowiek nie widział, CO
    faktycznie zostało zrobione (znaleziony 23.08.2026, patrz [[testowanie-mechanizmu-zadan-projectly]])."""
    notes = (execution_result or {}).get("acceptance_notes")
    wynik = f"\n📄 Wynik:\n{notes}\n" if notes else ""
    return (
        f"✅ done (przeszło bramkę jakości: zgody {gate['approvals']}/{gate['required']})\n"
        f"{gate['summary']}\n{wynik}Przypisano do: {owner}\n"
    )


def _comment_escalated(owner, reason):
    return f"⚠️ needs_approval\nWymaga decyzji: tak — {reason}\nUtworzono osobne zadanie dla: {owner}\n"


def _comment_subtask_done(owner, execution_result):
    """Podzadanie z dekompozycji — bez bramki jakości/eskalacji czerwonego
    ryzyka z zasady (decyzja właściciela 25.08.2026, patrz runner_loop.py
    _process_task_core: podzadania są z natury słabo opisane, ocena samej
    treści im nie służy)."""
    notes = (execution_result or {}).get("acceptance_notes")
    wynik = f"\n📄 Wynik:\n{notes}\n" if notes else ""
    return f"✅ done (podzadanie — bez bramki jakości, z zasady)\nPrzypisano do: {owner}\n{wynik}"


MAX_POPRAWEK = 2

# Zwroty, po których poznajemy, że problemem jest ZADANIE, a nie redakcja materiału.
# Przy nich poprawka nic nie da, bo brakuje danych albo polecenie jest niejasne.
_SYGNALY_ZLEGO_ZADANIA = (
    "nie wykonano", "brak zamówionego elementu", "źródło nie zawiera",
    "nie da się", "potrzebuję źródła", "nie odpowiada na zadanie",
)


def _popraw_i_sprawdz_ponownie(task, execution_result, gate):
    """Nanosi zastrzeżenia bramki na materiał i puszcza go przez bramkę jeszcze raz.

    Zwraca (gate, execution_result) — po poprawce albo bez zmian, gdy poprawka się
    nie udała. Limit prób jest twardy: po MAX_POPRAWEK zadanie idzie dalej swoją
    ścieżką, żeby agent nie kręcił się w kółko na materiale, którego nie umie
    naprawić."""
    for proba in range(1, MAX_POPRAWEK + 1):
        uwagi = gate.get("concerns") or []
        material = execution_result.get("acceptance_notes") or ""
        if not uwagi or not material or _zadanie_zle_postawione(execution_result, gate):
            return gate, execution_result

        wynik = poprawka_materialu.popraw(
            material, uwagi,
            zadanie=" ".join(str(task.get(k) or "") for k in ("title", "description")))
        if not wynik["available"]:
            state_store.log_decision(task["task_id"], agent="patrycja", decision="poprawka_nieudana",
                                     reason=wynik["powod"], now=now_iso(),
                                     cost_usd=wynik.get("cost_usd", 0.0))
            return gate, execution_result

        execution_result = {**execution_result, "acceptance_notes": wynik["material"],
                            "cost_usd": execution_result.get("cost_usd", 0.0) + wynik.get("cost_usd", 0.0)}
        state_store.log_decision(
            task["task_id"], agent="patrycja", decision=f"poprawka_{proba}",
            reason="Naniesiono uwagi odbioru: " + "; ".join(uwagi)[:400],
            now=now_iso(), event_type="execution", cost_usd=wynik.get("cost_usd", 0.0))

        gate = bot_gustaw_bramka.run_gate(task, execution_result)
        state_store.log_decision(
            task["task_id"], agent="gustaw",
            decision="gate_passed" if gate["passed"] else "gate_failed",
            reason=f"po poprawce {proba}: {gate['summary']}", now=now_iso(), event_type="quality_gate")
        if gate["passed"]:
            break
    return gate, execution_result


def _zadanie_zle_postawione(execution_result, gate):
    """Czy problem leży w ZADANIU (brak danych, niejasne polecenie), a nie w materiale.
    Wtedy poprawka redakcyjna nic nie da i nie ma po co zakładać zadania dla człowieka —
    wystarczy zamknąć z informacją, czego zabrakło."""
    material = (execution_result.get("acceptance_notes") or "").lower()
    if material.startswith("nie wykonano"):
        return True
    tekst = " ".join(str(c).lower() for c in (gate.get("concerns") or []))
    return any(sygnal in tekst for sygnal in _SYGNALY_ZLEGO_ZADANIA)


def _comment_zamkniete_z_feedbackiem(owner, execution_result, gate):
    """Komentarz zamykający zadanie, którego nie da się wykonać w tej postaci.
    Mówi wprost, czego zabrakło i co zrobić, żeby dało się je wykonać."""
    braki = "\n".join(f"- {c}" for c in (gate.get("concerns") or [])) or "- (brak szczegółów)"
    return (
        "🔒 zamknięte z feedbackiem — zadania nie da się wykonać w tej postaci\n"
        f"{execution_result.get('acceptance_notes') or ''}\n\n"
        f"Czego zabrakło:\n{braki}\n\n"
        "Nie zakładam osobnego zadania dla człowieka: popraw polecenie albo wskaż "
        f"właściwe źródło i wrzuć je ponownie. Przypisane do: {owner}"
    )


def _gate_failure_reason(gate):
    concerns = "; ".join(gate["concerns"]) or "brak szczegółów"
    return f"Bramka jakości nie przepuściła zadania. {gate['summary']} Zastrzeżenia: {concerns}"


# Flaga per PROCES (nie per przebieg) — True po pierwszym udanym pobraniu
# kolejki, zeruje się na każdym realnym restarcie (job_scheduler.py albo
# `python runner_loop.py --loop`), bo moduł jest importowany od nowa. Cel
# (żądanie właściciela 25.08.2026): jasno widoczne "ile mam do zrobienia" w
# logu ZARAZ po starcie bota, zanim jeszcze cokolwiek przetworzy — nie na
# każdym z kolejnych 30-sekundowych przebiegów (to byłby szum w logach).
_zalogowano_kolejke_przy_starcie = False


def _zaloguj_kolejke_przy_starcie(tasks):
    global _zalogowano_kolejke_przy_starcie
    if _zalogowano_kolejke_przy_starcie:
        return
    _zalogowano_kolejke_przy_starcie = True
    if not tasks:
        print("[runner_loop] Start — kolejka zadań: pusto.")
        return
    tytuly = ", ".join((t.get("title") or "?")[:40] for t in tasks[:10])
    wiecej = f" (+{len(tasks) - 10} więcej)" if len(tasks) > 10 else ""
    print(f"[runner_loop] Start — kolejka zadań: {len(tasks)}: {tytuly}{wiecej}")


def run_once(client=None):
    if kill_switch.is_active():
        print(f"Kill switch aktywny ({kill_switch.reason()}) — runner nie podejmuje akcji.")
        return []
    if control.is_paused():
        print(f"PAUSE ({control.pause_reason()}) — runner nie podejmuje nowej pracy.")
        return []

    budget = cost_tracker.budget_state()
    if budget["level"] != "ok":
        print(
            f"Budżet dobowy: {budget['level']} ({budget['percent']}%, "
            f"{budget['total']:.2f}/{budget['limit']:.2f} USD) — runner nie podejmuje nowej pracy."
        )
        heartbeat.write_heartbeat(current_task_id=None, extra={"budget": budget})
        return []

    policy = risk_classifier.load_policy()
    routing = task_router.load_routing()
    # client wstrzykiwany w testach (bootstrap_smoke_test wymusza mock, żeby test
    # mechanizmu był deterministyczny niezależnie od tego, czy live Projectly ma
    # akurat zadania). W produkcji None -> get_client() (mock albo realny wg .env).
    client = client or get_client()

    heartbeat.write_heartbeat(current_task_id=None)

    tasks = client.get_new_tasks()
    _zaloguj_kolejke_przy_starcie(tasks)
    razem = len(tasks)
    tasks, deferred = _wybierz_partie_wg_priorytetu(tasks)
    if deferred:
        print(f"{razem} nowych zadań — przetwarzam {len(tasks)} w tym przebiegu "
              "(najwyższy obecny priorytet, limit MAX_TASKS_PER_RUN), reszta zaczeka na kolejny poll.")
    results = []
    for task in tasks:
        heartbeat.write_heartbeat(current_task_id=task["task_id"])
        results.append(process_task(task, policy, routing, client))

    budget = cost_tracker.budget_state()
    heartbeat.write_heartbeat(current_task_id=None, extra={"budget": budget})
    # Rola z config/role.json (dev/marketing/zarząd...), NIE stały "dev" — inaczej
    # maszyna z inną rolą publikowałaby swój status na żywo pod cudzą etykietą
    # (żywy błąd, znaleziony 24.08.2026 przy rozszerzaniu statusu o kolejkę zadań).
    live_status_publisher.publish(
        client, role=env_bootstrap._current_role(),
        processed_tasks=[{"task_id": t["task_id"], "title": t.get("title", "")} for t in tasks],
        queued_tasks=[{"task_id": t["task_id"], "title": t.get("title", "")} for t in deferred],
    )

    if budget["level"] != "ok":
        print(
            f"UWAGA: budżet dobowy {budget['level']} ({budget['percent']}%) — "
            f"kolejny przebieg nie zacznie nowych zadań, dopóki się nie odnowi."
        )

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Ciągła pętla zamiast jednego przebiegu")
    parser.add_argument("--interval", type=int, default=30, help="Sekundy między przebiegami w trybie --loop")
    args = parser.parse_args()

    if not args.loop:
        results = run_once()
        for r in results:
            print(r)
        return

    print(f"Runner w trybie ciągłym, interwał {args.interval}s. Ctrl+C żeby zatrzymać.")
    try:
        while True:
            if kill_switch.is_active():
                print(f"Kill switch aktywny ({kill_switch.reason()}) — zatrzymuję runner.")
                sys.exit(0)
            for r in run_once():
                print(r)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Zatrzymano ręcznie.")


if __name__ == "__main__":
    main()
