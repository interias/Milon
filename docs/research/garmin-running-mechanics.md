# Laufmechanik und mechanische Belastung

Stand: 2026-10-05. Die Umsetzung verwendet lokale Garmin-Aufzeichnungen. Persönliche
Messreihen und GPS-Daten wurden nicht an externe Recherchedienste übermittelt.

## Einheiten und Herkunft

Garmin beschreibt Step Speed Loss als Geschwindigkeitsverlust beim Bodenkontakt,
SSL% als dessen Anteil an der Laufgeschwindigkeit. Das HRM 600 unterstützt diese
Messung; das Vorhandensein anderer Laufdynamik-Kanäle belegt allein kein bestimmtes
Sensormodell. [Garmin: Step Speed Loss](https://www.garmin.com/en-US/garmin-technology/running-science/running-dynamics/step-speed-loss/)

Eine lokal verfügbare Originalantwort enthält `directStepSpeedLossPercent`
(dimensionsloser Prozentwert), Bodenkontakt in `ms` und Schrittlänge in `centimeter`.
Diese optionalen Kanäle werden nur bei passendem Descriptor normalisiert. Dessen
`factor` wird nicht als allgemeine Umrechnung angewendet. Für absolutes SSL nennt
Garmin cm/s; der beobachtete JSON-Descriptor nennt jedoch `meter` mit `factor=100`.
Die Umsetzung verwendet deshalb SSL% und leitet keine absolute SSL-Einheit ab.

Impact Load ist eine Garmin-Schätzung mechanischer Beanspruchung, dargestellt als
äquivalente Distanz. Eine wöchentliche Summe ist nicht mit der zeitlich gewichteten
akuten Belastung gleichzusetzen. Die Lauftoleranz ist ebenfalls Garmins Schätzung,
keine individuelle Verletzungswahrscheinlichkeit oder sichere Trainingsobergrenze.
[Garmin: Running Tolerance](https://www.garmin.com/en-GB/garmin-technology/running-science/physiological-measurements/running-tolerance/)

In der untersuchten Originalantwort stimmt `impactLoad` mit dem Integral aus
Distanzmetern × dimensionslosem `directImpactLoadFactor` bis auf 0,18 % überein.
Milon bestätigt diese Einheit bei jeder importierten Aufzeichnung erneut:
mindestens 90 % Distanzabdeckung und höchstens 10 % Abweichung zum Integral.
Erst dann erscheint `impactLoad / 1000` als äquivalente Kilometer. Diese Grenzen
sind konservative Datenprüfungen, keine physiologischen Schwellenwerte.

## Frühe und späte Laufabschnitte

Die vorhandene Auswahl gleichmäßiger Minuten wird weiterverwendet: Einlaufen,
letzte Minuten, Pausen, Messlücken, variable Geschwindigkeit und zu steile
Abschnitte fallen heraus. Jeder zusätzliche Mechanik-Kanal benötigt mindestens
54 erfasste Sekunden pro Minute. Frühe und späte Minuten desselben Laufs werden
einmalig nach ähnlichem Tempo und ähnlicher Steigung gepaart. Mindestens sechs
Paare je Kennzahl sind die Darstellungsgrenze.

Die Oberfläche zeigt Mittelwerte, mittlere Differenz und die Spannweite der
gepaarten Differenzen. Jeder Minutenvergleich hat dasselbe Gewicht. Die
Verlaufskurve enthält alle geeigneten Minuten und lässt Lücken offen. Diese
Beschreibung ist kein Signifikanztest und beweist weder Ermüdung noch eine
Verbesserung der Technik. Andere Sensorperioden oder andere Läufe werden nicht
eingemischt.

## Wochenbelastung und optionale Toleranz

Die Wochenbalken vergleichen Distanz und Impact Load für genau dieselben
vollständigen, kanonischen Läufe. Fehlende Impact-Werte zählen nicht als null.
Mehrere Garmin-Zeilen derselben kanonischen Einheit zählen einmal. Hevy-Tage
mit protokollierten Bein-Arbeitssätzen erscheinen als separate Marker; es gibt
keine künstliche Umrechnung von Krafttraining in Laufkilometer. Die Zuordnung
nutzt die bestehende Muskelgruppen-Heuristik anhand des Übungsnamens.

Ein zentral koordinierter, authentifizierter Abruf von
`get_running_tolerance(..., aggregation="daily")` lieferte im verbundenen Konto
eine leere Liste. Das ist ein gültiger Leerzustand. Der optionale Import prüft
höchstens 90 Tage und höchstens alle sechs Stunden, bei manuellem Refresh sofort.
Fehler unterbrechen die übrigen Garmin-Importe nicht und erhalten frühere Werte.

Die installierte `garminconnect`-Bibliothek 0.3.17 bestätigt Endpunkt und Parameter.
Das Tagesformat `calendarDate`, `acuteTolerance`, `acuteImpactLoad`, `acuteDistance`
und dessen Meter-Skalierung sind zusätzlich im Quelltext einer unabhängigen
Implementierung dokumentiert; **gefüllte Tagesantworten wurden in diesem Konto
noch nicht verifiziert**. Milon akzeptiert nur valide Tage im angefragten Zeitraum
und endliche, begrenzte Zahlen; eine Toleranz muss positiv sein. Wöchentliche
Felder werden nicht als akute Tagesbelastung umgedeutet. Unbekannte Antworten
bleiben ohne Wert.
[Bibliotheksquelltext](https://github.com/cyberjunky/python-garminconnect/blob/0.3.17/garminconnect/__init__.py) ·
[Dokumentiertes Tagesformat](https://github.com/tamcore/garmin-mcp/blob/master/internal/garmin/api/runningtolerance.go)
