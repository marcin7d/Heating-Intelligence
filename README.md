# Heating Intelligence 0.1.1

[English documentation](README.en.md)

Lokalna integracja odczytowa dla Home Assistant Core 2026.11. Uczy się reakcji dowolnej liczby stref grzewczych i pokazuje rekomendacje. Automatyka kotła, termostatów i mieszacza pracuje niezależnie od integracji.

## Instalacja

1. Skopiuj `custom_components/heating_intelligence` do `/config/custom_components/`, zrestartuj Home Assistant.
2. **Ustawienia → Urządzenia i usługi → Dodaj integrację → Heating Intelligence**.
3. Wybierz co najmniej jedną encję `climate` (bez sztywnego limitu liczby stref), temperaturę zewnętrzną, zasilanie i powrót przy kotle oraz sygnał pracy kotła. Temperaturę za mieszaczem możesz pominąć. W drugim kroku zaznacz strefy podłogowe. Pozostałe strefy będą grzejnikowe.

### Marketplace i HACS

Repozytorium zawiera `hacs.json` w katalogu głównym. W Marketplace możesz dodać publiczny adres: https://github.com/marcin7d/Heating-Intelligence . Nie jest wymagane wydanie GitHub Release.

## Dane i wyniki

- Recorder powinien zapisywać wybrane encje wraz z atrybutami `climate`. Stan termostatu `hvac_action=heating` jest sygnałem zapotrzebowania. Przy braku atrybutu integracja szacuje zapotrzebowanie z niedogrzania o co najmniej 0,3°C w trybie grzewczym, automatycznym lub grzanie/chłodzenie, jeśli dostępna jest pojedyncza nastawa.
- Wybierz rzeczywisty sygnał palnika CO, jeśli go masz. Obsługiwane są stany `on/off`, `1/0`, `1.0/0.0`, `true/false`, `heating/idle` oraz `running` jako stan aktywny. Jeżeli podłączysz przekaźnik żądania, statystyki dotyczą jego cykli. Sygnał obejmujący CWU liczy również cykle CWU.
- Wspólne encje pokazują ΔT zasilanie–powrót w K, liczbę startów od lokalnej północy, minuty pracy, średni czas pełnego cyklu i pokrycie historią. ΔT opisuje różnicę temperatur przy kotle. Do wyznaczenia mocy w kW potrzebny byłby jeszcze przepływ.
- Każda strefa pokazuje temperaturę za 30, 60, 120 i 360 minut przy stałej temperaturze zewnętrznej i bieżącym poziomie ogrzewania. Osobna encja pokazuje, z jakim wyprzedzeniem rozpocząć grzanie przed planowaną godziną komfortu, dla aktualnej nastawy i szacowanej dostępnej mocy. Brak prognozy lub czasu dogrzania widać jako encję niedostępną.
- Model grzejników wykorzystuje temperaturę zasilania kotła. Model podłogówki wykorzystuje wodę za mieszaczem albo, przy braku wybranego czujnika, sygnał kotła jako przybliżenie dopływu ciepła. Oba modele uczą się osobnego współczynnika strat i pamięci cieplnej. Zmiana nastawy mieszacza pogarsza trafność modelu bez pomiaru za zaworem.
- Integracja przelicza wyniki co 5 minut. Model wykorzystuje do 7 dni Recorder, przyjmuje stan pomiędzy aktualizacjami i przerywa uczenie na jawnych brakach. Potrzebuje co najmniej 144 próbek treningowych oraz po 24 próbki niskiego i wysokiego dopływu ciepła. Ostatnie 20% próbek służy do doboru modelu i oceny błędu po 5 minutach względem prognozy stałej temperatury. Ta ocena nie mierzy błędu na 6 godzin. Parametry są przechowywane lokalnie i aktualizowane raz na dobę, a gdy brak modeli, co godzinę.
- Boiler Demand Manager sumuje niedogrzanie aktywnych stref, do 1 punktu na strefę. Rekomendacja uwzględnia łączny indeks, niedogrzanie pojedynczej strefy oraz niedawny start przy małym obciążeniu. Wykorzystuje obserwowane stany instalacji, bez wyznaczania minimalnego przepływu czy nastaw zabezpieczeń kotła.

## Testy

`python -m unittest discover -s tests -v` uruchamia testy modeli. Workflow dodatkowo uruchamia test dymny importów, kreatora i analizy danych z encji na obrazie Home Assistant Core 2026.11.0.

**Ograniczenia:** Wersja eksperymentalna; nie steruje żadnym urządzeniem i nie była jeszcze weryfikowana na fizycznej instalacji. Wyniki predykcji wymagają danych reprezentujących stany grzania i nie stanowią gwarancji oszczędności.
