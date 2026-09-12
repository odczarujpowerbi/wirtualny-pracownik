"""
Manifest polaczen maszyny: CO ta maszyna umie i czy to dziala.

Do Projectly (MCP zbot_report_connectors) leci WYLACZNIE opis i status:
nazwa, rodzaj, jedno zdanie po co to jest, "ok"/"brak"/"blad" i notatka.
Wartosci kluczy NIE wychodza z maszyny i nie ma ich w bazie Projectly —
decyzja wlasciciela 12.09.2026. W panelu widac wiec, ze MailerLite dziala,
ale nie widac, jaki ma klucz.

Dzieki temu czlowiek konfiguruje agenta z przegladarki (wlacz/wylacz, komu
udostepnic, przetestuj), nie logujac sie na maszyne, a sekrety zostaja tam,
gdzie byly.

Status liczymy z obecnosci zmiennych w srodowisku (env_bootstrap wczytuje
secrets/.env). "ok" = komplet zmiennych jest; realne potwierdzenie polaczenia
daje dopiero przycisk "Przetestuj" w Projectly, ktory zaklada zadanie testowe.
"""

import env_bootstrap  # noqa: F401  # wczytuje secrets/.env do srodowiska

import os

# (klucz, nazwa dla czlowieka, rodzaj, opis, wymagane zmienne)
POLACZENIA = [
    ("projectly", "Projectly", "mcp",
     "Zadania, projekty, dokumentacja i komentarze — glowny kanal pracy agenta.",
     ["PROJECTLY_API_KEY", "PROJECTLY_BASE_URL"]),
    ("poczta", "Poczta (Microsoft 365)", "api",
     "Wysylka i odczyt maili z konta firmowego.",
     ["MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_TENANT_ID", "MS_GRAPH_MAILBOX"]),
    ("sharepoint", "SharePoint i OneDrive", "system",
     "Foldery zadan i dokumenty firmowe.",
     ["ONEDRIVE_TASKS_ROOT"]),
    ("mailerlite", "MailerLite", "api",
     "Newslettery: statystyki kampanii i listy odbiorcow.",
     ["MAILERLITE_API_KEY"]),
    ("zoho_crm", "Zoho CRM", "mcp",
     "Kontakty, szanse sprzedazy i historia klienta.",
     ["ZOHO_CRM_MCP_TOKEN", "ZOHO_CRM_MCP_URL"]),
    ("zanfia", "Zanfia (kursy)", "mcp",
     "Platforma kursow online: zamowienia i uczestnicy.",
     ["ZANFIA_MCP_TOKEN", "ZANFIA_MCP_URL"]),
    ("github", "GitHub", "api",
     "Repozytoria projektow: zakladanie nowych i wysylka pracy agenta.",
     ["GITHUB_TOKEN"]),
    ("model_ai", "Model AI (Anthropic)", "api",
     "Zapasowy dostep do modelu, gdy Claude Code nie jest zalogowany.",
     ["ANTHROPIC_API_KEY"]),
]


def _status(wymagane):
    """"ok" gdy komplet zmiennych jest, "brak" gdy czegos brakuje."""
    brakujace = [z for z in wymagane if not (os.environ.get(z) or "").strip()]
    if not brakujace:
        return "ok", ""
    return "brak", f"brakuje: {', '.join(brakujace)}"


def zbuduj():
    """Manifest gotowy do wyslania. Bez zadnych wartosci sekretow."""
    manifest = []
    for klucz, nazwa, rodzaj, opis, wymagane in POLACZENIA:
        status, notatka = _status(wymagane)
        manifest.append({"key": klucz, "name": nazwa, "kind": rodzaj,
                         "description": opis, "status": status, "statusNote": notatka})
    return manifest


def zglos(client=None):
    """Wysyla manifest do Projectly. Nigdy nie rzuca — zwraca podsumowanie.

    Job harmonogramu (`connectors_report`) i panel operatora wolaja to samo."""
    manifest = zbuduj()
    dzialajace = [p["key"] for p in manifest if p["status"] == "ok"]
    wynik = {"polaczenia": len(manifest), "dzialajace": dzialajace, "wyslane": False, "powod": ""}

    if client is None:
        import projectly_client
        client = projectly_client.get_client()

    try:
        client.report_connectors(manifest)
        wynik["wyslane"] = True
    except Exception as exc:  # noqa: BLE001 — raport statusu nie moze ubic harmonogramu
        wynik["powod"] = f"nie udalo sie wyslac manifestu do Projectly: {exc}"
    return wynik


if __name__ == "__main__":
    for polaczenie in zbuduj():
        print(f"{polaczenie['status']:5} {polaczenie['name']:28} {polaczenie['statusNote']}")
