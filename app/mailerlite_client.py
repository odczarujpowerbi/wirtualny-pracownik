"""
Konektor do MailerLite REST API (config/integrations.yaml wpis `mailerlite`).

UWAGA UCZCIWA: dokładne ścieżki endpointów poniżej są najlepszym
przybliżeniem z publicznej dokumentacji znalezionej przez wyszukiwarkę w
tej sesji — bezpośredni dostęp do developers.mailerlite.com był
zablokowany przez proxy sieciowe, więc nie czytałem specyfikacji 1:1.
Zweryfikuj dokładne ścieżki/parametry w oficjalnej dokumentacji przed
poleganiem na tym na produkcji.

Potwierdzone (WebSearch, patrz historia rozmowy): kampanie mają pełny
zapis (draft/harmonogram/wysyłka/anulowanie) i statystyki (otwarcia,
kliknięcia, rezygnacje, odbicia) dostępne przez API.
"""

import os

import requests

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem MAILERLITE_API_KEY

BASE_URL = "https://connect.mailerlite.com/api"


class MailerLiteClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    def get_campaigns_sent_since(self, since_iso_date):
        """Zwraca listę wysłanych kampanii od danej daty (RRRR-MM-DD, włącznie).

        ZWERYFIKOWANE na koncie produkcyjnym (2026-08-22): `filter[since]` NIE
        istnieje w REST MailerLite — wcześniejsza wersja tej funkcji zwracała
        400 Bad Request. `filter[status]=sent` działa; data jest filtrowana
        PO STRONIE KLIENTA po `finished_at`, stronicując, dopóki nie trafimy
        kampanii starszej niż `since_iso_date` (API domyślnie sortuje
        najnowsze-najpierw — potwierdzone na tym koncie, nie w dokumentacji)."""
        results = []
        page = 1
        while True:
            response = requests.get(
                f"{BASE_URL}/campaigns",
                headers=self._headers,
                params={"filter[status]": "sent", "limit": 50, "page": page},
                timeout=15,
            )
            response.raise_for_status()
            body = response.json()
            campaigns = body.get("data", [])
            if not campaigns:
                break

            reached_older = False
            for campaign in campaigns:
                finished = campaign.get("finished_at") or campaign.get("scheduled_for") or ""
                if finished and finished[:10] < since_iso_date:
                    reached_older = True
                    break
                results.append(campaign)
            if reached_older:
                break

            meta = body.get("meta", {})
            if page >= meta.get("last_page", page):
                break
            page += 1
        return results

    def get_campaign_stats(self, campaign_id):
        response = requests.get(f"{BASE_URL}/campaigns/{campaign_id}", headers=self._headers, timeout=15)
        response.raise_for_status()
        return response.json().get("data", {})


class MockMailerLiteClient:
    """Do testów bez prawdziwego klucza — czyta mock_data/sample_mailerlite_campaigns.json."""

    def __init__(self, campaigns_path=None):
        from pathlib import Path

        self.campaigns_path = campaigns_path or Path(__file__).parent / "mock_data" / "sample_mailerlite_campaigns.json"

    def get_campaigns_sent_since(self, since_iso_date):
        import json

        with open(self.campaigns_path, encoding="utf-8") as f:
            return json.load(f)

    def get_campaign_stats(self, campaign_id):
        campaigns = self.get_campaigns_sent_since(None)
        for c in campaigns:
            if c["id"] == campaign_id:
                return c
        return {}


def get_mailerlite_client():
    api_key = os.environ.get("MAILERLITE_API_KEY")
    if api_key:
        return MailerLiteClient(api_key)
    return MockMailerLiteClient()
