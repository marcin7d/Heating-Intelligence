# Heating Intelligence 0.2.0 — wersja robocza

**NIEOPUBLIKOWANA.** Rozwojowa wersja integracji Home Assistant 2026.11 — wyłącznie monitorowanie i predykcja. Nie wykonuje żadnych komend do kotła, mieszacza ani termostatów.

## Konfigurator

Wybierasz dowolną niezerową liczbę encji `climate`, czujniki temperatury zewnętrznej, zasilania i powrotu kotła, sygnał pracy kotła oraz opcjonalną temperaturę za mieszaczem. Dodatkowo możesz wybrać **promieniowanie W/m²**, **oświetlenie lux** oraz **moc PV W**. W kolejnym kroku wskazujesz strefy podłogowe, a dla każdej strefy orientację okien (N/E/S/W) i stopień zacienienia.

### Wykorzystanie słońca

Pierwszeństwo ma czujnik promieniowania W/m². Lux i moc PV są **wskaźnikami zastępczymi**, nie pomiarami napromienienia okien; nie są sumowane z W/m². Położenie słońca jest odczytywane z `sun.sun`. Każda strefa ma oddzielny współczynnik wpływu słońca. Model z nasłonecznieniem musi obniżyć błąd walidacyjny co najmniej o 3% względem modelu bazowego. Jeżeli czujniki słońca nie istnieją, model bazowy może nadal działać.

### Diagnostyka stref

- `Model training status`: `insufficient_history`, `missing_heating_cycles`, `validation_failed`, `ready`, `ready_solar`, `retained_old_model`, `missing_recent_data`, `not_trained`
- `Model samples`: liczba próbek wybranego modelu lub ostatniej próby
- `Model validation MAE (5 min)`: średni błąd walidacyjny na odłożonym fragmencie historii, dla kroku 5 minut
- `Solar exposure index`, `Solar gain coefficient`, `Solar data source`, `Solar model active`
- Prognozy temperatury na 30/60/120/360 minut i zalecany czas wyprzedzenia nagrzewania

Integracja wykorzystuje historię Recorder (do 7 dni) i aktualizuje wyniki co 5 min. Modele są zapisywane w `.storage`. Pomiary za mieszaczem są opcjonalne; jeśli ich nie ma, podłogówka wykorzystuje przybliżenie z pracy kotła. Prognoza na 6 godzin zakłada utrzymanie bieżących warunków, w tym nasłonecznienia, dlatego **nie jest pełną prognozą przyszłego słońca**.

## Instalacja testowa

Skopiuj `custom_components/heating_intelligence/` do `/config/custom_components/heating_intelligence/`, zrestartuj HA i dodaj integrację przez UI. **Uwaga:** kreator w tej wersji nie zawiera migracji poprzedniej konfiguracji 0.1.1; przetestuj na osobnej instancji lub kopii zapasowej, zanim ją podmienisz.

## Walidacja

```bash
python -m compileall -q custom_components tests
python -m unittest discover -s tests -v
```

Testy jednostkowe nie są równoznaczne z testem integracyjnym na działającym Home Assistant 2026.11. Dodatkowo nadal potrzebna będzie walidacja prognoz 60/360 min w warunkach rzeczywistych.

## Nowy profil: **Kuchnia** (0.2.0 — nadal robocza)

Podczas konfiguracji każdej strefy wybierz **Room profile → kitchen / Kuchnia**. Profil pomieszczenia jest **niezależny** od typu obiegu (grzejniki/podłogówka). Pozostałe pomieszczenia mają profil `standard`.

Dla kuchni możesz opcjonalnie podłączyć **moc piekarnika** i **płyty** (W lub kW), **stan okapu** (`binary_sensor`/`switch`) oraz **wilgotność w kuchni** (%). Puste pola są dozwolone. Integracja wykrywa dodatkowe zyski ciepła przez:

- moc piekarnika lub płyty **≥ 150 W** (nie wykrywa urządzeń gazowych bez dodatkowego sygnału),
- aktywny okap — sygnał aktywności kuchennej, który może też wynikać z samej wentylacji,
- wzrost wilgotności o **≥ 6 punktów procentowych w ciągu 5 minut**,
- wzrost temperatury o **≥ 0,25°C w ciągu 5 minut**, lecz **tylko** gdy wskaźniki ogrzewania oraz nasłonecznienia są znane i niskie.

Wykryte okresy i kolejne **30 minut** są **pomijane w danych do treningu** (nie znikają z Recorder). Podczas zdarzenia i wychładzania po zdarzeniu prognozy kuchni oraz `Recommended preheat lead` są tymczasowo niedostępne, ponieważ model nie prognozuje ciepła z gotowania. **Pozostałe pomieszczenia nadal działają normalnie**. Gdy zakłócenie ustąpi, model zaczyna ponownie prognozować bez utraty zapisanych współczynników.

Nowe encje dla stref:

| Encja (nazwa w urządzeniu) | Co oznacza |
|---|---|
| `Room profile` | `standard` albo `kitchen` |
| `Kitchen internal heat` | `active`, `cooldown`, `none`, `not_applicable` |
| `Kitchen heat source` | `oven`, `hob`, `hood`, `humidity_rise`, `unexpected_warming`, `none` |
| `Kitchen training samples excluded` | Liczba pominiętych próbek podczas ostatniego treningu |
| `Kitchen heat events in training window` | Liczba rozpoznanych początków zdarzeń w ostatnim oknie treningowym |

**Ograniczenia:** to detektor przeszkadzających zysków wewnętrznych, nie pomiar mocy cieplnej gotowania ani prognoza tego, kiedy domownicy będą gotowali. Niewielkie, wolno zmieniające się zyski mogą pozostać niewykryte. Bez dodatkowych czujników i bez dostępnego wskaźnika słońca wykrywanie jest ograniczone. Zamknięcie okapu nie oznacza, że ciepło już zniknęło. Progi są eksperymentalne i wymagają weryfikacji na danych rzeczywistych.

**Uwaga dotycząca aktualizacji:** dla istniejącej konfiguracji 0.2.0 konfigurator nie obsługuje jeszcze edycji profili przez opcje integracji. Przed testowaniem profilu Kuchnia zapisz kopię konfiguracji i dodaj integrację od nowa. Nie zalecam podmieniania produkcyjnej 0.1.1 bez kopii zapasowej.

## Diagnostyka braku prognoz — robocze 0.2.0

Po uruchomieniu treningu w encjach każdego pomieszczenia dostępne są:

- **Model training status** — m.in. `ready`, `ready_solar`, `insufficient_valid_samples`, `insufficient_heating_samples`, `insufficient_idle_samples`, `no_temperature_variation` lub `validation_failed`.
- **Model valid history rows** i **Model total history rows** — liczba kompletnych i wszystkich pięciominutowych próbek w oknie treningowym.
- **Model missing room/outdoor/heat rows** — diagnostyka brakujących źródeł.
- **Model heating samples** oraz **Model idle samples** — poprawne pary treningowe; próg wymagany przez algorytm to minimum 24 każdego rodzaju.
- **Model temperature changes** — liczba wykrytych zmian temperatury o co najmniej około 0,05°C na następujących po sobie poprawnych próbkach.
- **Model candidate validation MAE** oraz **Model constant-temperature baseline MAE** — błąd najlepszego kandydata i modelu zakładającego stałą temperaturę. Jeśli kandydat nie jest lepszy, jego prognoza nadal pozostaje niedostępna.
- **Last model training attempt (Unix UTC)** — znacznik czasu próby w sekundach od epoki UNIX.

Trening ponawia się co godzinę, dopóki choć jedna skonfigurowana strefa nie ma modelu. Po zaakceptowaniu modeli dla wszystkich stref następuje co 24 godziny. Samo `Recorder history = available` nie oznacza, że wszystkie strefy mają kompletną historię.

**Uwaga:** ta paczka jest wersją roboczą, niepublikowaną. Testy jednostkowe nie zastępują sprawdzenia na prawdziwym Home Assistant; przed podmianą plików wykonaj kopię zapasową konfiguracji. Aktualizacja istniejącej integracji nie dodaje automatycznie nowych opcji konfiguratora (np. profilu kuchni), jeśli integracja była skonfigurowana wcześniej.
