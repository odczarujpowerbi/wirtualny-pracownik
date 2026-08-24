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
from datetime import datetime, timezone
from pathlib import Path

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env (patrz .env.example, bootstrap_init_secrets.py)

import bot_gustaw_bramka
import control
import cost_tracker
import document_builder
import executor
import heartbeat
import kill_switch
import poprawka_materialu
import live_status_publisher
import report_builder
import risk_classifier
import risk_hint
import skill_usage_logger
import state_store
import task_router
import task_thinker
import validator_prompt
from escalation import escalate_to_human
from projectly_client import _load_config as _load_projectly_config
from projectly_client import get_client

HINT_TO_ACTION = {
    "green": "read_report",
    "yellow": "report_build",
    "red": "budget_change",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _escalation_assignee():
    """Kto ma dostać zadanie eskalacji w Projectly — config/projectly.yaml
    `escalation_default_assignee`, NIGDY 'owner' z task_router.route_task().
    'owner' jest routing biznesowy/klienta (do jakiego klienta należy zadanie),
    nie osoba do powiadomienia — dla nierozpoznanego tytułu route_task zwraca
    'unassigned_pool', co przez people_aliases mapuje się na "" (brak
    przypisania). Skutek namacalny 23.08.2026: WSZYSTKIE eskalacje (nowe i
    historyczne) trafiały do Projectly z assignees=[] — niewidoczne dla
    człowieka, nikt nie wiedział, że czekają na decyzję."""
    try:
        return _load_projectly_config().get("escalation_default_assignee", "pawel")
    except Exception:  # noqa: BLE001 — config nieczytelny nie może zablokować eskalacji
        return "pawel"


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

    Gdy `execution_result` niesie dane tabelaryczne (`table_rows`, np. lista
    kampanii MailerLite z integracje_worker.raport_mailerlite) — decyzja
    właściciela 24.08.2026: obok wynik.md ma zawsze powstać analiza.xlsx,
    bez osobnej zgody, ten sam standard co dla wynik.md.

    Fail-soft: brak ONEDRIVE_TASKS_ROOT albo błąd zapisu NIE MOŻE zablokować
    przetwarzania zadania — to dodatkowy ślad, nie krytyczny krok pipeline'u.
    Zwraca ścieżkę folderu albo None, gdy nie zapisano.

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
        data = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        folder = root_path / f"{task['task_id']}_{data}_{_slug(task.get('title', ''))}"
        sections = [
            {"heading": "Status", "text": status},
            {"heading": "Wynik", "text": comment},
        ]
        document_builder.build_md(task.get("title") or "Zadanie", sections, folder / "wynik.md")
        rows = execution_result.get("table_rows") if execution_result else None
        if rows:
            title = execution_result.get("table_title") or task.get("title") or "Analiza"
            report_builder.write_xlsx_report(title, rows, folder / "analiza.xlsx")
        return str(folder)
    except Exception:  # noqa: BLE001 — zapis dodatkowy, błąd nie może ubić przetwarzania zadania
        return None


def process_task(task, policy, routing, client):
    """Przetwarza zadanie i oznacza DOMKNIĘCIE BLOKU (block_closed) przy statusie
    końcowym — to granica bezpiecznego resetu kontekstu: brief kolejnych zadań nie
    wciąga zamkniętego (task_brief_builder). Audyt zostaje, kontekst przestaje ciągnąć."""
    result = _process_task_core(task, policy, routing, client)
    if result and result.get("status") in ("done", "needs_approval"):
        state_store.record_event(result["task_id"], "block_closed", result["status"], now_iso())
    return result


def _process_task_core(task, policy, routing, client):
    task_id = task["task_id"]
    now = now_iso()

    state_store.upsert_task(task_id, payload=task, status="planning", now=now)
    state_store.record_event(task_id, "task_received", task["title"], now)

    # Sprawdzenie bezpieczeństwa treści PRZED klasyfikacją ryzyka — wykryta
    # próba wstrzyknięcia eskaluje zawsze, niezależnie od koloru zadania
    # (dokumentacja bazowa 9.4: tekst zewnętrzny to dane, nie polecenie).
    prompt_check = validator_prompt.check_prompt_safety(task.get("title", ""))
    state_store.record_event(task_id, "prompt_safety_check", str(prompt_check), now_iso())
    if not prompt_check["safe"]:
        owner, _ = task_router.route_task(task["title"], routing)
        escalate_to_human(task, f"Wykryto podejrzaną treść: {prompt_check['detail']}", client,
                          assignee=_escalation_assignee())
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

    # Realny worker, jeśli istnieje dla tego typu zadania (dziś: walidacja PBIP).
    # Gdy None — zostaje dotychczasowa ścieżka "sama klasyfikacja", nic nie udajemy.
    real = executor.execute(task)
    if real is not None:
        execution_result = {**real, "thinking": thinking,
                            "cost_usd": real.get("cost_usd", 0.0) + thinking.get("cost_usd", 0.0)}
        state_store.log_decision(
            task_id, agent="patrycja", decision=real["tool"],
            reason=real["acceptance_notes"], now=now_iso(),
            event_type="execution", cost_usd=real.get("cost_usd", 0.0),
        )
    else:
        execution_result = {
            "cost_usd": thinking.get("cost_usd", 0.0),
            "acceptance_notes": thinking.get("reasoning") or "Brak modelu — sama klasyfikacja/routing.",
            "thinking": thinking,
        }
    cost_tracker.record_cost(task_id, execution_result["cost_usd"])

    # Worker odmówił wykonania (np. ścieżka poza dozwolonym katalogiem roboczym) —
    # to zdarzenie bezpieczeństwa, eskalujemy wprost, nie przez bramkę jakości
    # (nie podajemy podejrzanej ścieżki dalej do botów).
    if real is not None and real.get("executed") is False:
        reason = real["acceptance_notes"]
        escalate_to_human(task, reason, client, assignee=_escalation_assignee())
        state_store.log_decision(task_id, agent="pawel", decision="escalate", reason=reason,
                                 now=now_iso(), event_type="escalation")
        state_store.upsert_task(task_id, payload=task, status="needs_approval",
                                assigned_to=owner, risk_level=risk, now=now_iso())
        komentarz = _comment_escalated(owner, reason)
        client.post_comment(task_id, komentarz)
        client.update_status(task_id, "needs_approval")
        _save_result_to_onedrive(task, "needs_approval", komentarz, execution_result)
        return {"task_id": task_id, "risk": risk, "owner": owner, "status": "needs_approval"}

    if risk == "red":
        reason = "Czerwona akcja — poza zakresem tego szkieletu, brak jeszcze zdefiniowanej bounded_red do sprawdzenia."
        escalate_to_human(task, reason, client, assignee=_escalation_assignee())
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
            escalate_to_human(task, reason, client, assignee=_escalation_assignee())
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

    client.post_comment(task_id, comment)
    client.update_status(task_id, status)
    _zapisz_feedback(client, task_id, status, execution_result, risk)
    _save_result_to_onedrive(task, status, comment, execution_result)

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
        zapis(task_id, feedback=tresc)
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
    results = []
    for task in tasks:
        heartbeat.write_heartbeat(current_task_id=task["task_id"])
        results.append(process_task(task, policy, routing, client))

    budget = cost_tracker.budget_state()
    heartbeat.write_heartbeat(current_task_id=None, extra={"budget": budget})
    live_status_publisher.publish(client, role="dev")

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
