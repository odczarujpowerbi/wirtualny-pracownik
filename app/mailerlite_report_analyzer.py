"""
Cotygodniowy raport z maili wysłanych przez MailerLite — teksty, tytuły,
czytelność, klikalność (PLAN-WDROZENIA.md sekcja 21). Analogiczny wzorzec
do ad_performance_analyzer.py: czysty Python liczy to, co da się policzyć
(statystyki, heurystyka czytelności), model wchodzi dopiero do subiektywnej
oceny (ton, jakość tytułu) — i tylko jeśli jest klucz API.

Czego CELOWO brakuje: ocena WYGLĄDU maila (sekcja 21) wymaga wyrenderowania
HTML do obrazu (Playwright, jeszcze niezainstalowany w tym repo — patrz
requirements.txt) i przepuszczenia przez walidator wizualny
(validators.py::_call_vision_model). Bez tego kroku raport ocenia tylko
tekst i statystyki, nie layout.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

import model_registry
from mailerlite_client import get_mailerlite_client
from projectly_client import get_client


def _plain_text(campaign):
    return campaign.get("plain_body") or re.sub("<[^>]+>", " ", campaign.get("html_body", ""))


def analyze_readability(text):
    """Prosta, deterministyczna heurystyka (bez AI): długość zdań i słów.
    Nie jest to certyfikowany indeks czytelności dla języka polskiego —
    wystarczający sygnał do wykrycia oczywistych problemów (jedno zdanie
    na cały akapit, ściana tekstu)."""
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sentences:
        return {"avg_words_per_sentence": 0, "longest_sentence_words": 0, "flag": "brak tekstu do analizy"}

    words_per_sentence = [len(s.split()) for s in sentences]
    avg = sum(words_per_sentence) / len(words_per_sentence)
    longest = max(words_per_sentence)

    flag = None
    if avg > 20:
        flag = "przeciętne zdanie jest długie (>20 słów) — może obniżać czytelność"
    elif longest > 35:
        flag = f"najdłuższe zdanie ma {longest} słów — warto rozbić"

    return {"avg_words_per_sentence": round(avg, 1), "longest_sentence_words": longest, "flag": flag}


def compute_stats(campaign):
    sent = campaign.get("sent_count", 0)
    opens = campaign.get("opens", 0)
    clicks = campaign.get("clicks", 0)
    return {
        "open_rate": round(opens / sent, 4) if sent else 0,
        "ctr": round(clicks / sent, 4) if sent else 0,
        "click_to_open_rate": round(clicks / opens, 4) if opens else 0,
    }


def ai_feedback(subject, body_text):
    """Subiektywna ocena tonu/jakości tytułu — wymaga modelu. Bez klucza:
    jasny stub, nie zmyślona opinia (fail-closed, ten sam wzorzec co
    validators.py i ad_copy_generator.py)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "Brak ANTHROPIC_API_KEY — pomięto subiektywną ocenę tonu/tytułu (dostępna tylko statystyka i heurystyka czytelności)."

    try:
        import anthropic
    except ImportError:
        return "Pakiet 'anthropic' niezainstalowany — pomięto ocenę subiektywną."

    prompt = (
        f"Tytuł maila: {subject}\n\nTreść:\n{body_text}\n\n"
        "Oceń w 2-3 zdaniach: czy tytuł zachęca do otwarcia, czy treść jest "
        "klarowna i angażująca, i jedną konkretną rzecz do poprawy następnym razem."
    )
    client = anthropic.Anthropic()
    _, model = model_registry.resolve("mailerlite_report_analyzer.analyze")
    response = client.messages.create(model=model, max_tokens=250, messages=[{"role": "user", "content": prompt}])
    return response.content[0].text.strip()


def build_report(campaigns):
    lines = ["📧 Raport MailerLite — tygodniowy przegląd wysłanych maili", ""]
    for c in campaigns:
        stats = compute_stats(c)
        readability = analyze_readability(_plain_text(c))
        feedback = ai_feedback(c["subject"], _plain_text(c))

        lines.append(f"### {c['subject']}")
        lines.append(
            f"- Statystyki: open rate {stats['open_rate']*100:.1f}%, CTR {stats['ctr']*100:.2f}%, "
            f"click-to-open {stats['click_to_open_rate']*100:.1f}%"
        )
        lines.append(
            f"- Czytelność: śr. {readability['avg_words_per_sentence']} słów/zdanie, "
            f"najdłuższe zdanie {readability['longest_sentence_words']} słów"
            + (f" ⚠️ {readability['flag']}" if readability["flag"] else "")
        )
        lines.append(f"- Ocena treści/tytułu: {feedback}")
        lines.append("- Ocena wyglądu (layout): ⏸ nie zaimplementowane w tym szkielecie — wymaga renderowania HTML (Playwright) i walidatora wizualnego")
        lines.append("")

    return "\n".join(lines)


def run_weekly_report(client=None, mailerlite_client=None):
    client = client or get_client()
    mailerlite_client = mailerlite_client or get_mailerlite_client()

    since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    campaigns = mailerlite_client.get_campaigns_sent_since(since)

    report_text = build_report(campaigns)
    client.post_comment("MAILERLITE-WEEKLY-REPORT", report_text)
    return report_text


if __name__ == "__main__":
    print(run_weekly_report())
