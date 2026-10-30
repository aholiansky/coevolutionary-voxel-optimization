# Dane wysokościowe B0 z pracy inżynierskiej

Pliki w tym katalogu są niezmienionymi artefaktami wejściowymi starego algorytmu B0. 
Zostały zachowane do testów zgodności, a nie jako docelowy model statystyczny pracy magisterskiej.

## Pochodzenie

- skrypt źródłowy: `legacy/analyzer.py`,
- źródłowy świat Minecraft: niedostępny,
- promień zapisany w kodzie analizatora: 50 chunków,
- dostępne dane odpowiadają 9489 przeskanowanym przekrojom chunków na warstwę.

Brak świata uniemożliwia sprawdzenie, czy statystyki powstały z czystego coveru.
Z tego powodu model ma etykietę `legacy/suspect-provenance`.

## Kontrola spójności

`ore_stats_raw.csv` zawiera 384 uporządkowane warstwy od Y=-64 do Y=319.
Wartości surowe zgadzają się z licznikami bloków, pięciowarstwowe wygładzanie zostało poprawnie odtworzone, a JSON jest identyczny z wygładzonymi kolumnami CSV.

Wykryte ostrzeżenia:

1. Na Y=-63 zapisano 6161 bloków rudy, po czym aż do Y=-3 prawie cały zakres pozostaje bez rudy. Bez świata nie da się ustalić źródła tego skoku.
2. Prawdopodobieństwo 0.068966 na Y=115 opiera się na zaledwie 116 blokach nośnika, więc jest niestabilne statystycznie.
3. Wygładzanie z zerowym dopełnieniem nadaje dodatnie prawdopodobieństwo warstwom bez żadnego bloku nośnika, m.in. Y=-64, Y=116 i Y=117.

Model może być używany do odtwarzania B0, ale nowe eksperymenty powinny wyznaczać rozkład z jawnie zapisanych seedów treningowych i oceniać go na oddzielnych seedach testowych.

