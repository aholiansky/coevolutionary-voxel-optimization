# MCStego - baseline badawczy do pracy magisterskiej

To jest uporządkowana baza projektu rozwijającego kod z pracy inżynierskiej.
Oryginalne pliki zostały zachowane bez zmian w `legacy/`. 
Nowy kod w `src/` wydziela algorytm B0 od formatu świata Minecraft i operacji wejścia/wyjścia.

## Co już działa

- deterministyczna nawigacja zgodna z B0 (warstwa Y, następnie spirala kwadratowa),
- model prawdopodobieństwa `P(coal | Y)`,
- osadzanie i ekstrakcja bitów na abstrakcyjnym wolumenie bloków,
- ślad każdej modyfikacji: pozycja, bit, blok przed i po,
- adapter pamięciowy do szybkich eksperymentów,
- metryka oczekiwanej zmiany częstości rudy,
- zamrożony model wysokościowy i surowe statystyki z inżynierki,
- automatyczna kontrola spójności `ore_distribution.json` z CSV,
- powtarzalny generator świeżych światów Minecraft Java 1.21.5,
- zamrożony pilot seedów `8 train / 2 validation / 3 sealed test`,
- kontrola kompletności 1024 chunków bez zależności od komunikatów konsoli,
- manifest i sumy kontrolne każdego niemodyfikowanego świata,
- bezpośredni, tylko do odczytu importer regionów Anvil z Minecrafta 1.21.5,
- deterministyczny format kostek `.mcvx` z jawną paletą i proweniencją,
- testy bez Minecrafta i bez biblioteki Amulet.

## Szybki start

```bash
python -m unittest discover -s tests -v
```

Walidacja danych legacy:

```bash
python scripts/validate_legacy_ore_data.py
```

Walidacja nowego rejestru seedów i podgląd planu:

```bash
python scripts/worldgen.py registry
python scripts/worldgen.py plan --split train
```

Na Windows cały proces uruchamiają kolejno:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\00-doctor.ps1
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\01-bootstrap.ps1 -AcceptEula
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\02-generate.ps1 -Split train
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\02-generate.ps1 -Split validation
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\03-verify.ps1 -Split train
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\03-verify.ps1 -Split validation
```

Nie generować splitu `test` przed zamrożeniem algorytmu, hiperparametrów i rocedury ewaluacji. Pełna instrukcja: `docs/WORLD_GENERATION.md`.

Kontrola świata i próbna ekstrakcja kostki `32³`:

```powershell
python .\scripts\voxel_import.py inspect `
  --world .\worlds\train\train-001

python .\scripts\voxel_import.py extract `
  --world .\worlds\train\train-001 `
  --output .\runs\voxels\train-001-x-16-y-48-z-16-s32.mcvx `
  --origin -16 -48 -16 `
  --size 32
```

Importer najpierw sprawdza sumy SHA-256 coveru i nigdy go nie zapisuje.
Specyfikacja formatu i zasady doboru próbek: `docs/VOXEL_IMPORT.md`.

Opcjonalna instalacja w środowisku wirtualnym:

```bash
python -m pip install -e .
```

## Układ projektu

```text
legacy/                    niezmieniony kod z inżynierki
src/mcstego/core/          typy, granice obszaru i nawigacja
src/mcstego/strategies/    algorytmy ukrywania (obecnie B0)
src/mcstego/adapters/      nośniki danych (obecnie pamięć)
src/mcstego/experiments/   metryki i przyszły runner eksperymentów
tests/                     testy regresyjne rdzenia
docs/                      audyt i decyzje architektoniczne
data/legacy/               niezmienione dane wejściowe B0 + metadane
config/                     przypięty toolchain i publiczny rejestr seedów
src/mcstego/worldgen/       walidacja, generator, manifesty i kontrola Anvil
src/mcstego/voxels/         odczyt Anvil i deterministyczne kostki MCVX
windows/worldgen/           bezpieczne wejścia PowerShell dla Windows
```  
    
## Ważna interpretacja B0

B0 jest baseline'em historycznym, a nie metodą uznaną z góry za statystycznie niewykrywalną. 
Jeśli naturalna częstość rudy wynosi `p`, slot jest wybierany z częstością `q`, 
a zaszyfrowany payload zawiera około 50% jedynek, to oczekiwana częstość rudy po osadzeniu wynosi:

```text
p_after = (1 - q) * p + q * 0.5
```

W historycznej konfiguracji `q = p`, więc `p_after = 1.5p - p²`. Efekt musi być mierzony empirycznie, a nie zakładany.

Szczegóły i lista dalszych prac: `docs/PHASE_0_AUDIT.md`.
