# Konfiguracje modeli lokalnych (Ollama)

Pliki `Modelfile.*` to nakladki na modele bazowe: ustawiaja parametry
generowania i prompt systemowy, nie zawieraja wag. Budowa jest natychmiastowa
i nie zajmuje dodatkowego miejsca — warstwy sa wspoldzielone z modelem bazowym.

## Budowanie

    ollama create llama-pl -f instalacja/modele/Modelfile.llama-pl

Po kazdej zmianie pliku trzeba powtorzyc te komende — `ollama create`
nadpisuje istniejacy model o tej nazwie.

## Co jest w srodku

| plik | model bazowy | RAM | przeznaczenie |
|---|---|---|---|
| `Modelfile.llama-pl` | `llama3.2:3b` | ~3,1 GB | maszyny bez GPU (domyslny) |
| `Modelfile.hermes-pl` | `hermes3` | ~6,0 GB | maszyny z GPU lub >16 GB RAM |

Oba maja `temperature 0.3` (zadania techniczne, powtarzalnosc zamiast
kreatywnosci) i prompt systemowy po polsku, ktory wymusza zwiezlosc oraz
przyznawanie sie do niewiedzy zamiast zgadywania.

## Uwagi

- `num_thread 3` jest dobrane pod maszyne z 3 rdzeniami. Na innym sprzecie
  ustaw liczbe rdzeni albo usun te linie (Ollama wykryje sama).
- `num_ctx 8192` to bezpieczny sufit przy 12 GB RAM. KV cache rosnie liniowo:
  ok. 0,16 GB na kazde 1000 tokenow kontekstu dla modelu 8B.
- Stop tokeny roznia sie miedzy rodzinami modeli: `hermes3` uzywa ChatML
  (`<|im_start|>`), `llama3.2` formatu naglowkow Llama-3 (`<|eot_id|>`).
  Skopiowanie ich miedzy plikami psuje generowanie.
- Te pliki NIE ustawiaja modelu uzywanego przez aplikacje. Aplikacja czyta
  `OLLAMA_TEXT_MODEL` i `OLLAMA_VISION_MODEL` z `app/secrets/.env`, a modele
  bazowe pobiera `instalacja/skrypty/bootstrap_install_local_model.ps1`.
