# Kontekst firmowy — jedno miejsce, z którego agent bierze osadzenie

Tu leży wiedza o firmie, której **nie da się wyczytać z kodu ani z treści zadania**:
kto jest kim, co sprzedajemy, do kogo mówimy, jakim językiem i czego nigdy nie
obiecujemy. Bez tego agent wykonuje zadania poprawnie technicznie, ale obok
realiów firmy.

## Jak to działa

`kontekst_firmy.py` wczytuje te pliki i dokleja właściwy fragment do promptu przy
analizie zadania, pisaniu treści i odbiorze biznesowym. Marka dobierana jest po
treści zadania (nazwa marki, projekt, słowa kluczowe); gdy nic nie pasuje, agent
dostaje sam plik `firma-podstawy.md`.

Dopisanie akapitu tutaj działa od następnego zadania — to konfiguracja, nie kod.

## Pliki

| Plik | Co zawiera |
|---|---|
| `firma-podstawy.md` | Kto jest kim, jak mają się do siebie marki, zasady wspólne dla obu |
| `marka-odczaruj-power-bi.md` | Marka szkoleniowa: oferta, odbiorcy, język |
| `marka-clickless.md` | Marka wdrożeniowa: usługi, cennik, proces, obietnice |
| `wydarzenie-power-bi-day.md` | Konferencja: terminy, bilety, program |
| `projekty/` | Kontekst pojedynczych projektów i klientów (osobny plik na projekt) |

## Zasady prowadzenia tych plików

1. **Krótko.** Każdy plik ma się zmieścić w prompcie razem z zadaniem. Jeśli rośnie
   ponad ~150 linii, znaczy że część należy do pliku projektu, nie do marki.
2. **Fakty, nie marketing.** Wpisujemy to, co pomaga podjąć decyzję albo napisać
   poprawną treść. Slogany tylko jako wskazówka tonu.
3. **Oznaczaj niepewne.** Wszystko, czego nie potwierdził właściciel, ma dopisek
   `[do potwierdzenia]`. Agent traktuje to jako hipotezę, nie jako fakt do cytowania.
4. **Ceny i terminy się zmieniają.** Przy każdej liczbie ma stać data ustalenia.
   Agent nie podaje ceny klientowi bez sprawdzenia aktualnej na stronie.

Źródło pierwszej wersji: strony odczarujpowerbi.pl, powerbiday.com.pl i clickless.pl,
odczytane 20.08.2026.
