# Import wokseli z Minecraft Java 1.21.5

## Cel i granica odpowiedzialności

Importer zamienia jawnie wskazany obszar niemodyfikowanego świata `cover` na kanoniczną kostkę wokseli. Czyta bezpośrednio pliki regionów Java Anvil `.mca` oraz binarny NBT. Nie uruchamia Minecrafta, nie wymaga Amuleta i nie ma operacji zapisu do świata źródłowego.

Przed każdym `inspect` i `extract` program:

1. wymaga `mcstego-world-manifest.json` z `immutable_cover=true`;
2. sprawdza SHA-256 `level.dat` i wszystkich regionów zapisanych w manifeście;
3. porównuje seed, wersję Minecrafta oraz DataVersion z `level.dat`;
4. przy ekstrakcji wymaga finalnego statusu każdego użytego chunka;
5. odrzuca wynik umieszczony wewnątrz katalogu coveru.

Jakakolwiek zmiana coveru kończy operację błędem. Plik wynikowy należy trzymać w `runs/voxels/` albo innym katalogu artefaktów, nigdy w `worlds/`.

## Użycie na Windows

Sprawdzenie świata i pionowego zakresu zapisu:

```powershell
python .\scripts\voxel_import.py inspect `
  --world .\worlds\train\train-001
```

Ekstrakcja kostki o boku 32 bloków:

```powershell
python .\scripts\voxel_import.py extract `
  --world .\worlds\train\train-001 `
  --output .\runs\voxels\train-001-x-16-y-48-z-16-s32.mcvx `
  --origin -16 -48 -16 `
  --size 32
```

Prostokątny wolumen można wskazać przez `--shape X Y Z` zamiast `--size N`.
Domyślnie paleta zachowuje pełny stan bloku, np. `minecraft:deepslate_redstone_ore[lit=false]`. 
Wariant `--state-mode name` usuwa właściwości i zachowuje tylko nazwę bloku.

Kontrola gotowego artefaktu:

```powershell
python .\scripts\voxel_import.py verify `
  --artifact .\runs\voxels\train-001-x-16-y-48-z-16-s32.mcvx
```

Istniejący wynik nie jest domyślnie nadpisywany. Flaga `--overwrite` musi być podana jawnie.

## Specyfikacja MCVX, schema 1

`.mcvx` jest archiwum ZIP bez kompresji, ze stałą kolejnością wpisów i stałymi znacznikami czasu. Ten sam świat, obszar i tryb stanów dają identyczne bajty.

| Wpis | Zawartość |
|---|---|
| `metadata.json` | geometria, kodowanie, proweniencja i SHA-256 payloadów |
| `palette.json` | tablica kanonicznych nazw lub pełnych stanów bloków |
| `voxels.u16le` | identyfikatory palety jako little-endian `uint16` |

Kształt i początek są zapisywane jako `[X, Y, Z]`. Kolejność liniowa ma `Z` jako najszybszą oś:

```text
index = ((x * size_y) + y) * size_z + z
```

Paleta jest lokalna dla artefaktu:

- id `0` zawsze oznacza `minecraft:air`;
- pozostałe, faktycznie występujące stany są sortowane leksykograficznie;
- identyfikator o tej samej wartości w dwóch plikach nie musi oznaczać tego samego bloku;
- przed treningiem wiele kostek należy przemapować do jednego, zamrożonego słownika klas.

Metadane źródła obejmują identyfikator świata, split, seed, wersję Minecrafta, hash manifestu i hashe plików coveru. Dzięki temu kostkę można jednoznacznie powiązać ze źródłem bez dołączania wielogigabajtowego świata.

## Zasady eksperymentalne

- Jednostką splitu pozostaje cały seed świata. Kostki z `train-001` są tylko treningowe, nawet jeśli pochodzą z odległych chunków.
- `validation` nie służy do aktualizacji modelu, słownika ani statystyk rewardu.
- `test` pozostaje zapieczętowany do końcowej ewaluacji.
- Współrzędne są obecnie jawne. Politykę losowania wielu kostek zamrozimy osobno, razem z rozmiarem, zakresem Y, marginesem oraz seedem samplera.
- MCVX jest artefaktem audytowym i wejściem do testów offline. Środowisko RL może korzystać bezpośrednio z `AnvilWorldReader`, więc nie wymaga materializacji całego statycznego datasetu.

## Zakres zgodności

Implementacja obsługuje nowoczesne sekcje `block_states` oraz kompresję zlib, gzip i brak kompresji w regionach Anvil. 
Pilot został zweryfikowany dla Minecraft Java 1.21.5, DataVersion 4325. Nietypowe chunki LZ4 są odrzucane jawnym błędem zamiast ryzykownego, cichego odczytu.
