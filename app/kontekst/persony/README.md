# Buyer persony — realne profile odbiorców treści marketingowych

Kopia realnych profili buyer person z OneDrive ("Buyer persony Odczaruj PBI",
"Buyer persony clickless/personas"), po jednym pliku na osobę. Używane przez
`ad_copy_generator.py` do pisania treści pod konkretną personę (nie
generycznie "napisz dobry tekst", tylko pod profil TEJ konkretnej osoby).

## Struktura

```
persony/
  odczaruj/    — 02-pawel-...md, 03-kasia-...md, 04-zuzanna-...md, 05-tomek-...md, 06-joanna-...md
  clickless/   — 01-marek-...md, 02-roman-...md, ..., 07-krzysztof-...md
```

Nazwa pliku: `NN-imię-opis.md`. **Imię jest kluczem dopasowania** —
`kontekst_firmy.dopasuj_persone(target_persona, brand)` szuka pliku, którego
imię (drugi segment nazwy) występuje w `target_persona`.

## Ważne: imiona kolidują między markami

Obie marki mają personę o imieniu **„Tomek"** — inny profil u Odczaruj
(analityk obawiający się stagnacji) i inny u Clickless (sceptyk techniczny).
Dlatego dopasowanie **wymaga** znanej marki (`brand="odczaruj"` albo
`"clickless"`) — bez niej `dopasuj_persone` zwraca `None` (fail-closed:
lepiej brak profilu niż profil złej osoby).

## Skąd bierze się `target_persona` w wyniku generatora

`ad_copy_generator.generate_variants(brief, brand=...)` zwraca
`{"brand": ..., "variants": [{"target_persona": "Kasia", ...}, ...]}` — model
sam mówi, do której z załadowanych person pisze. (Wcześniej te pola czytała
też bramka jakości przy ocenie trafności persony — ten bot został usunięty,
pola zostają tylko jako metadana generatora.)

## Aktualizacja

Te pliki to **kopia** — źródło jest w OneDrive. Gdy właściciel zmieni/dopisze
personę tam, trzeba ją skopiować tutaj ręcznie (albo dopisać do
`kontekst_projektow_seed.py`-podobnego generatora, jeśli person przybędzie
na tyle, że ręczna synchronizacja przestanie się skalować).
