# Powtarzalne generowanie światów — pilot 8/2/3

## Zamrożona specyfikacja

| Element | Wartość |
|---|---|
| Minecraft | Java Edition 1.21.5 |
| Java | 21 |
| Loader | Fabric Loader 0.16.10 |
| API wymagana przez Chunky | Fabric API 0.119.5+1.21.5 |
| Pre-generator | Chunky Fabric 1.4.36, Modrinth `mhLtMoLk` |
| Wymiar | wyłącznie Overworld |
| Generator | `minecraft:normal`, struktury włączone |
| Docelowy obszar | chunki X=-16…15, Z=-16…15 |
| Rozmiar analityczny | 32 × 32 = 1024 chunki na świat |
| Splity | 8 train / 2 validation / 3 sealed test |

Wersje wynikają z ciągłości z inżynierką. Fabric oficjalnie wskazywał Loader 0.16.10 dla Minecrafta 1.21.5, a wydanie Chunky 1.4.36 jest oznaczone jako zgodne z 1.21.5/Fabric:

- <https://fabricmc.net/2025/03/24/1215.html>
- <https://modrinth.com/mod/fabric-api/version/0.119.5%2B1.21.5>
- <https://modrinth.com/plugin/chunky/version/mhLtMoLk>
- <https://github.com/pop4959/Chunky/wiki/Commands>

Fabric i Chunky służą wyłącznie do wymuszenia wygenerowania chunków. Nie ma datapacków ani modów zmieniających teren. Pierwszy bootstrap zapisuje sumy SHA-256 pobranych plików, a pierwszy start zamraża również wszystkie rozwiązane pliki JAR runtime'u. Następne uruchomienia odmawiają pracy, jeśli którykolwiek element toolchainu się zmieni.

## Zasada podziału danych

Jednostką podziału jest **seed świata**, nie chunk ani kostka 3D. Chunków z jednego świata nie wolno rozdzielać pomiędzy train, validation i test, ponieważ prowadziłoby to do przecieku wspólnych cech generatora oraz sąsiedniego terenu.

- `train`: uczenie RL, budowa statystyk naturalnego świata i uczenie Eve;
- `validation`: wybór hiperparametrów, rewardu i checkpointu;
- `test`: jeden końcowy pomiar po zamrożeniu całej metody.

`config/seeds.public.json` zawiera jawne seedy train/validation. Dla testu zawiera tylko trzy zobowiązania SHA-256. Właściwe seedy i losowe nonce są w osobnym pliku. Kod sprawdza zobowiązania przed odblokowaniem testu.

Wszystkie 13 wartości wylosowano z systemowego CSPRNG jako liczby signed 64-bit. Odrzucono wyłącznie zero i duplikaty; światów nie oglądano przed przydzieleniem do splitów, więc nie występuje ręczny dobór „ciekawych” seedów.

Pliku prywatnego nie należy umieszczać w repozytorium, katalogu treningowym, logach ani przekazywać procesowi RL. Sam fakt, że badacz może go przechowywać, nie jest przeciekiem — istotne jest, że żaden etap projektowania lub uczenia nie korzysta ze światów testowych.

## Dlaczego analizujemy dokładnie te 1024 chunki

Docelowy prostokąt bloków to X=-256…255 i Z=-256…255. Chunky otrzymuje te rogi, a walidator niezależnie sprawdza tablicę lokalizacji w plikach Anvil `.mca`.
Proces kończy się dopiero, gdy wszystkie wpisy dla chunków X=-16…15, Z=-16…15 wskazują na kompletne sektory pliku.

Serwer może utworzyć kilka dodatkowych chunków, np. wokół naturalnego spawnu.
Nie należą one do korpusu i są ignorowane przez eksperyment. 
Dzięki jawnej ROI każdy świat wnosi dokładnie 1024 chunki analityczne.

## Uruchomienie na Windows

Rozpakować publiczny pakiet projektu do katalogu z odpowiednią ilością wolnego miejsca. 
Crystal Launcher nie musi być uruchomiony i nie należy kopiować do projektu jego kont, tokenów ani całego folderu.

### 1. Diagnostyka

Skrypty wejściowe `.ps1` używają wyłącznie znaków ASCII, dzięki czemu są poprawnie parsowane także przez Windows PowerShell 5.1 niezależnie od systemowej strony kodowej.

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\00-doctor.ps1
```

Skrypt sprawdza:

- Python 3.10+;
- Javę 21 w `JAVA_HOME`, `PATH` albo pod `C:\Apps\Crystal-Launcher`;
- dostępną pamięć i miejsce na dysku;
- możliwość utworzenia wydzielonego runtime'u.

Raport trafia do `runs/worldgen/doctor.json`. Nie zawiera loginów ani danych sesji launchera. Jeśli automatyczne wykrycie Javy nie zadziała:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\00-doctor.ps1 `
  -JavaPath "C:\pełna\ścieżka\do\bin\java.exe"
```

### 2. Bootstrap

Uruchom:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\01-bootstrap.ps1 -AcceptEula
```

Skrypt pobierze przypięty launcher serwera Fabric i wskazany artefakt Chunky, zweryfikuje metadane moda oraz utworzy `runtime/worldgen/toolchain.lock.json`.
Minecraft nie wymaga uruchamiania GUI ani danych konta.

### 3. Generowanie train i validation

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\02-generate.ps1 -Split train
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\02-generate.ps1 -Split validation
```

Można wygenerować pojedynczy świat:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\02-generate.ps1 `
  -Split train -WorldId train-001
```

Przerwanie `Ctrl+C`, restart systemu albo błąd nie usuwa nieukończonego świata. Ponowne wywołanie dla tego samego identyfikatora wznawia zadanie.
Skrypt nigdy nie nadpisuje świata należącego do innego seedu.

### 4. Weryfikacja

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\03-verify.ps1 -Split train
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\03-verify.ps1 -Split validation
```

Kontrolowane są:

- wszystkie 1024 wpisy chunków w regionach Anvil;
- seed zapisany w `level.dat`;
- wersja Minecrafta zapisana w `level.dat`;
- manifest świata;
- sumy SHA-256 `level.dat` i docelowych plików regionów.

Każdy poprawny świat znajduje się w `worlds/<split>/<world-id>` i zawiera `mcstego-world-manifest.json`.

## Otwieranie testu — dopiero na końcu

Najpierw należy zamrozić:

1. implementację B0/EA/RL;
2. reward i hiperparametry;
3. checkpoint modelu;
4. metryki i progi decyzyjne;
5. procedurę uszkodzeń i liczbę powtórzeń.

Dopiero wtedy użyć osobnego pliku prywatnego:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\worldgen\02-generate.ps1 `
  -Split test `
  -UnlockTestSet `
  -TestKeyPath "D:\bezpieczne\mcstego-test-seeds-private-v0.2.0.json"
```

Weryfikacja testu wymaga tych samych dwóch parametrów. Flaga ma być jawna, aby splitu testowego nie dało się użyć przypadkiem.

## Zasady pracy ze światami cover

- Po wygenerowaniu nie otwierać coveru w kliencie Minecraft.
- Nie uruchamiać na nim Injectora ani Amuleta w trybie zapisu.
- Każdy eksperyment tworzy osobną kopię coveru do katalogu runu.
- Gdy suma kontrolna coveru się zmieni, walidacja ma zakończyć się błędem.
- Nowe statystyki rudy wolno liczyć z train; validation/test nie mogą wpływać na model bazowy ani reward.
- Historyczne `data/legacy/ore_distribution.json` pozostaje wyłącznie modelem B0 z inżynierki i nie zastępuje statystyk nowego korpusu.

## Artefakty po wygenerowaniu

```text
runtime/worldgen/                  przypięty serwer i lock toolchainu
worlds/train/train-001/            niemodyfikowany świat cover
worlds/validation/validation-001/  niemodyfikowany świat cover
worlds/test/test-001/              istnieje dopiero po odblokowaniu testu
runs/worldgen/logs/                logi generowania
runs/worldgen/generation-status.json
runs/worldgen/verification-*.json
```

Katalogi `runtime/`, `worlds/`, `runs/` i `private/` są wyłączone z kontroli wersji, ponieważ mogą być duże albo zawierać zapieczętowane dane testowe.
