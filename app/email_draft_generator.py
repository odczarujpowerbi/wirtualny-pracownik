"""
Generator draftów maili z gotowych szablonów komunikacji z klientem
(`templates/email/*.md`) — przygotowanie pod dostęp do skrzynki Microsoft
365, o który poprosiłeś (config/integrations.yaml wpis `microsoft_365`).
Działa już dziś w trybie mock (zapisuje draft do pliku, nic nie wysyła);
po dostarczeniu dostępu wystarczy dopisać `EmailClient` w
`email_client.py` — reszta pipeline'u się nie zmienia.

Wzorzec identyczny jak `ad_copy_generator.py`: czysty szablon + podstawienie
zmiennych działa zawsze; opcjonalne dopracowanie tonu przez model tylko
jeśli jest ANTHROPIC_API_KEY (fail-closed — bez klucza zwracamy surowy,
ale kompletny i sensowny draft, nie zmyśloną poprawkę).
"""

import os
import re
from pathlib import Path

import model_registry
from email_client import get_email_client

TEMPLATES_DIR = Path(__file__).parent / "templates" / "email"


def list_templates(templates_dir=TEMPLATES_DIR):
    return sorted(p.stem for p in templates_dir.glob("*.md"))


def load_template(name, templates_dir=TEMPLATES_DIR):
    path = templates_dir / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Brak szablonu '{name}'. Dostępne: {', '.join(list_templates(templates_dir))}")
    return path.read_text(encoding="utf-8")


def render_template(name, **template_vars):
    text = load_template(name)
    for key, value in template_vars.items():
        text = text.replace("{{" + key + "}}", str(value))

    missing = re.findall(r"\{\{(\w+)\}\}", text)
    if missing:
        raise ValueError(f"Szablon '{name}' ma niewypełnione placeholdery: {', '.join(sorted(set(missing)))}")
    return text


def _split_subject_body(rendered):
    lines = rendered.splitlines()
    if lines and lines[0].startswith("Temat:"):
        subject = lines[0][len("Temat:") :].strip()
        body = "\n".join(lines[1:]).strip()
        return subject, body
    return "(brak tematu w szablonie)", rendered


def ai_polish(body_text):
    """Opcjonalne dopracowanie tonu — bez klucza zwraca tekst bez zmian,
    nie zmyśloną poprawkę (ten sam wzorzec co mailerlite_report_analyzer.ai_feedback)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return body_text
    try:
        import anthropic
    except ImportError:
        return body_text

    prompt = (
        "Popraw ton i płynność poniższego maila po polsku, zachowaj wszystkie fakty "
        "i nie zmieniaj nic w nawiasach klamrowych, jeśli jakieś zostały:\n\n" + body_text
    )
    client = anthropic.Anthropic()
    _, model = model_registry.resolve("email_draft_generator.generate")
    response = client.messages.create(model=model, max_tokens=600, messages=[{"role": "user", "content": prompt}])
    return response.content[0].text.strip()


def generate_draft(template_name, to, cc=None, polish=False, email_client=None, action="draft", **template_vars):
    """`action='draft'` (domyślnie) zapisuje draft, nic nie wysyła.
    `action='send'` faktycznie wysyła — a więc przechodzi przez
    `resolve_send_recipients` w email_client.py (zawsze do człowieka
    wewnątrz firmy, patrz config/email_safety.yaml), nie bezpośrednio do `to`."""
    rendered = render_template(template_name, **template_vars)
    subject, body = _split_subject_body(rendered)
    if polish:
        body = ai_polish(body)

    client = email_client or get_email_client()
    if action == "send":
        path = client.send_email(to=to, subject=subject, body_text=body, cc=cc)
    else:
        path = client.save_draft(to=to, subject=subject, body_text=body, cc=cc)
    return {"path": path, "subject": subject, "body": body, "action": action}


if __name__ == "__main__":
    print("Dostępne szablony:", list_templates())
    result = generate_draft(
        "client_onboarding_summary",
        to="klient@przyklad.pl",
        firma="Przykładowa Sp. z o.o.",
        imie="Marku",
        marka="Odczaruj Power BI",
        zakres="Model danych + raport zarządczy",
        nastepny_krok="Warsztat zbierania wymagań",
        termin="w przyszłym tygodniu",
        nadawca="Paweł",
    )
    print("\nZapisano draft:", result["path"])
    print("\n--- Podgląd ---")
    print(f"Temat: {result['subject']}\n\n{result['body']}")
