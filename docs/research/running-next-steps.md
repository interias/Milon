# Nächste sinnvolle Lauf-Funktionen

Stand: 2026-10-05. Recherche anhand des aktuellen Codes, der installierten
`garminconnect`-Version 0.3.17 und Primärquellen. Keine persönlichen Messwerte oder
Routen wurden für diese Recherche an externe Dienste übermittelt.

**Umsetzungsstand:** Referenzrunde und freiwillige Laufabsicht sind umgesetzt.
Stationswetter wurde im verbundenen Konto geprüft und wird direkt importiert:
Temperatur (Fahrenheit → Celsius), Feuchte, Windrichtung und Messzeit. `windSpeed`
enthält keine Einheit; weder Bibliothek noch untersuchte Original-FIT-Aufzeichnung
konnten sie belegen. Deshalb wird keine Geschwindigkeit behauptet oder umgerechnet.
Fehlende Werte bleiben unbekannt, bisherige Wetterwerte nach Abruffehlern erhalten.
Der übrige Text hält den Recherche-Ausgangspunkt und die methodischen Grenzen fest.

## Ausgangspunkt

Milon zeigt bereits Trainingswirkung, Pulsstabilität, standardisierten Puls-Trend,
Pulszonen, Runden, Laufdynamik, einen Vergleich zweier Läufe sowie Wochenvolumen
und Bestzeiten. Die nächsten Funktionen sollten daraus verständliche persönliche
Vergleiche machen, statt weitere Kennzahlen hinzuzufügen.
[Architektur](../../ARCHITECTURE.md) · [Laufanalysen](../../server/app/metrics/run_insights.py) ·
[Garmin-Normalisierung](../../server/app/garmin_activity.py)

## 1. Eine persönliche Referenzrunde

**Frage:** „Wird meine gewohnte Runde bei ähnlichem Aufwand leichter?“

Eine vorhandene Runde als Referenz markieren. Milon sammelt passende Wiederholungen
und zeigt eine kurze Entwicklung: Puls bei vergleichbarer Pace, tatsächliche
Vergleichsdaten und Anzahl der geeigneten Läufe. Ein Klick öffnet bei Bedarf den
bestehenden Detailvergleich. Neu wären die beständige Vergleichsgruppe über Monate
und die individuelle Streuung; der vorhandene Vergleich zweier Läufe bleibt die
technische Grundlage.

**Heute vorhanden:** Zeit, Puls, Tempo, Höhe, GPS und qualitätsgeprüfte Minuten.
**Zusätzlich nötig:** Auswahl einer Referenzrunde und eine feste Vergleichsdefinition
für Richtung, Abschnitt, Dauer und Sensorperiode. Keine neue Datenquelle erforderlich.
Die Runde muss kein schneller Testlauf sein. Anfangs einzelne Beobachtungen zeigen;
eine verlässliche persönliche Schwankungsbreite muss erst aus Wiederholungen entstehen.

**Evidenz und Grenze:** Sangan et al. untersuchten einen standardisierten submaximalen
Laufbandtest an 40 trainierten Ausdauerläufern; elf absolvierten Wiederholungen.
Pace und Puls zeigten brauchbare Wiederholbarkeit. Das stützt standardisierte
Vergleiche, validiert aber weder eine beliebige Außenrunde noch Milons Algorithmus.
Die Autoren fordern bei anderen Bedingungen oder Sensoren eine eigene Prüfung
der Wiederholbarkeit. Kleine einzelne Verbesserungen daher zunächst als Beobachtung
zeigen, nicht als bewiesenen Fitnessgewinn.
[Originalstudie und Autorenfassung](https://durham-repository.worktribe.com/output/1245124/the-self-paced-submaximal-run-test-associations-with-the-graded-exercise-test-and-reliability)

**Priorität:** hoch; größter Nutzen mit den bereits importierten Daten.

## 2. „Gut gelaufen“ am eigenen Trainingsziel einordnen

**Frage:** „Hat dieser Lauf das erfüllt, was ich wollte?“

Ein optionales Ziel wie „locker“, „lang“ oder „Tempo“ ergänzen und die bereits
vorhandene Anstrengungsangabe direkt am Lauf verwenden. Die Einordnung könnte
beispielsweise „Locker geplant · ähnlich schnell · leichter empfunden“ lauten.
Ein niedriger Trainingsreiz muss bei einem bewusst lockeren Lauf kein Misserfolg
sein. Das ist eine vorgeschlagene Produktlogik, kein validierter Gesamtscore.
[Garmin erklärt unterschiedliche Trainingswirkungen verschiedener Laufarten](https://www.garmin.com/en-AU/garmin-technology/running-science/physiological-measurements/training-effect/)

**Heute vorhanden:** freiwilliger Check-in mit Energie, Anstrengung von 1–5 und
optionaler Zuordnung zu einer Einheit. **Zusätzlich nötig:** strukturiertes
Trainingsziel und die Darstellung des vorhandenen Check-ins am Lauf. Kein zweites
Pflichtformular. Das aktuelle Modell speichert einen Check-in pro Tag; mehrere
Einheiten desselben Tages benötigen eine bewusste spätere Modellentscheidung.
[Check-in-Modell](../../server/app/checkins.py)

Garmin bietet ebenfalls eine freiwillige Bewertung von Anstrengung und Gefühl
und beschreibt sie ausdrücklich als Vergleichshilfe für ähnliche Trainings.
Die Garmin-Anstrengungsskala von 1–10 ist nicht identisch mit Milons 1–5-Skala.
Ein späterer Import muss Quelle und Originalskala erhalten; aktuell werden diese
Garmin-Felder in Milon nicht normalisiert. Ihre konkrete Abrufbarkeit im verbundenen
Konto wurde hier nicht geprüft.
[Garmin: Self Evaluation](https://support.garmin.com/en-US/?faq=8nISJXqSZVAI3Td4IWRqsA)

**Priorität:** hoch; verbessert die Interpretation, ohne die Oberfläche aufzublähen.

## 3. Bedingungen beim Vergleich sichtbar machen

**Frage:** „War ich schlechter, oder waren die Bedingungen anders?“

Am bestehenden Vergleich kleine Hinweise zu Temperatur, Wind und Datenherkunft
anzeigen, sofern Garmin sie liefert. Bei deutlich unterschiedlichen Bedingungen
den Vergleich vorsichtiger formulieren. Keine universelle Formel, die eine vermeintlich
„wetterbereinigte“ Pace errechnet.

**Heute vorhanden:** Geländeprofil, Tageszeit und Sensorgrenzen.
**Import fehlt:** Aktivitätswetter. Die installierte Bibliothek besitzt
`get_activity_weather(activity_id)`; Milons Import ruft die Methode noch nicht auf.
Das belegt eine technische Schnittstelle, nicht gefüllte Werte im Nutzerkonto.
Vor Umsetzung müssen Rückgaben, Einheiten, Messzeit und Herkunft lokal geprüft werden.
Garmin-Aktivitätsdaten zuerst nutzen, statt GPS an einen zusätzlichen Wetterdienst
zu übertragen.
[Versionierter Bibliotheksquelltext](https://github.com/cyberjunky/python-garminconnect/blob/0.3.17/garminconnect/__init__.py#L3320-L3326) ·
[Aktueller Import](../../server/app/garmin_activity.py)

**Evidenz und Grenze:** In einer kontrollierten Feldstudie mit 17 Läufern beeinflusste
der Hydratationszustand beim Laufen in Wärme den Puls auch bei vergleichbarem Tempo.
Das begründet Vorsicht beim Gleichsetzen von höherem Puls mit schlechterer Fitness.
Wetterdaten messen jedoch weder die individuelle Flüssigkeitsbilanz noch die
Temperatur entlang jedes Streckenabschnitts; sie erklären einen Unterschied nicht
automatisch.
[Originalstudie](https://pmc.ncbi.nlm.nih.gov/articles/PMC2838466/)

**Priorität:** mittel; sinnvoller Kontext für die Referenzrunde, nach Prüfung der Daten.

## Bewusst zurückgestellt

Ein zusätzlicher „Durability“-Score würde momentan weitgehend die bereits vorhandene
Pulsdrift umbenennen. Laborbefunde zeigen zwar, dass sich die Ermüdungsresistenz bei
längerem Laufen zwischen Trainingsgruppen unterscheiden kann. Daraus folgt aber
kein validierter persönlicher Schwellenwert für beliebige kurze Alltagsläufe.
Erst bei ausreichend langen, wiederholbaren Aufzeichnungen wäre ein Verlauf später
Laufabschnitte eine eigenständige Erweiterung.
[Originalstudie: Unhjem, 2024](https://doi.org/10.1111/sms.14637)

Ein neues Gesamtrating, feste „gute“ Driftgrenzen und automatisch verordnete
Trainingssteigerungen sind durch diese Recherche nicht begründet. Die drei
Vorschläge oben ergänzen die bestehenden Ansichten mit Vergleichbarkeit und Bedeutung.
