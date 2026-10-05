# Laufvergleich mit Streuung

Stand: 2026-10-05. Recherche anhand von Primärquellen und der vorhandenen
[Laufanalyse](../../server/app/metrics/run_insights.py). Persönliche Messwerte und
Routen wurden nicht an externe Dienste übermittelt.

## Entscheidung

Der ausgewählte Lauf wird automatisch allen passenden anderen Läufen derselben
Strecke gegenübergestellt. Zwei kompakte Verteilungen zeigen **Pace** und
**Durchschnittspuls**. Jeder andere Lauf zählt einmal; der ausgewählte Lauf ist
deutlich markiert und gehört nicht zur Berechnung der Vergleichsverteilung.
Das beantwortet „Wo liegt dieser Lauf in meiner bisherigen Streuung?“ ohne
manuelle Auswahl eines Vergleichslaufs.

Median, unteres und oberes Quartil sowie Minimum und Maximum beschreiben Lage und
Streuung. Der Bereich zwischen den Quartilen umfasst die mittleren 50 % der
Beobachtungen; er ist kein Konfidenzintervall. Für Milon sind die Enden ausdrücklich
Minimum und Maximum, keine automatisch abgeschnittenen Ausreißergrenzen.
[NIST: Box Plot](https://itl.nist.gov/div898/handbook/eda/section3/boxplot.htm)

**Darstellungsregeln von Milon:**

- Keine passenden Läufe: ehrlicher Leerzustand; Überdeckungsgrenze nicht absenken.
- Ein Vergleichslauf: einzelner Punkt und direkte Differenz, keine Streuung behaupten.
- Zwei bis vier: alle Einzelpunkte, Median und beobachtete Spanne.
- Ab fünf: zusätzlich eine dezente Quartilsfläche; Einzelpunkte bleiben sichtbar.

Die Grenze von fünf ist eine Entscheidung für verständliche Darstellung, keine
wissenschaftliche Grenze für Zuverlässigkeit. Die Quartile sollten mit einer
festen, getesteten Methode berechnet werden, etwa `numpy.quantile(method="linear")`;
dies interpoliert zwischen benachbarten geordneten Beobachtungen.
[NumPy: quantile](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html)

## Was „97 % gleiche Strecke“ bedeutet

GPS-Punkte stimmen bei wiederholten Aufzeichnungen nicht exakt überein. Die
Empfangsqualität hängt unter anderem von Abschattung, Reflexionen und dem Empfänger
ab; die Genauigkeit des Satellitensignals ist nicht die Positionsgenauigkeit der Uhr.
[GPS.gov: GPS Accuracy](https://www.gps.gov/gps-accuracy-0)

Eine Prozentangabe benötigt deshalb eine eigene überprüfbare Definition. Empfohlen
ist eine **beidseitige, nach Streckenlänge gewichtete Überdeckung**: Wie viel von
Strecke A liegt innerhalb eines festgelegten Meterabstands zu B, und umgekehrt?
Der kleinere Anteil entscheidet. Eine kurze Teilstrecke innerhalb einer langen
Runde gilt damit nicht automatisch als derselbe Lauf. Gleichmäßig entlang der
Distanz gesetzte Prüfpunkte verhindern, dass Pausen mit vielen GPS-Punkten das
Ergebnis dominieren.

Zusätzlich sind Laufrichtung, ähnliche Gesamtdistanz und durchgehende verwertbare
GPS-Aufzeichnung erforderlich. Eine zweite Runde auf identischem Weg darf nicht
als einfacher Durchlauf gelten. Lücken dürfen nicht mit erfundenen geraden
Verbindungen geschlossen werden. Gegenläufige Runden können dasselbe Gebiet
abdecken, aber ein anderes Belastungsprofil haben.

Das sind technische Auswahlregeln für Milon, keine extern validierte
„97-%-Norm“. In der Methodenbeschreibung stehen Überdeckungsgrenze,
Meter-Toleranz und Richtungsprüfung ausdrücklich nebeneinander. Synthetische
Tests müssen GPS-Rauschen, Umwege, Teilstrecken, Gegenrichtung, Zusatzrunden und
Lücken abdecken; echte lokale Routen prüfen anschließend die Praxistauglichkeit.

Die Umsetzung verwendet 30 m GPS-Toleranz und längengewichtete 20-m-Abschnitte.
Der niedrigere der beiden Überdeckungsanteile entscheidet. GPS-Pfadlängen und
gemeldete Distanzen müssen jeweils ein Verhältnis von mindestens 97 % haben.
Lokale Richtungen dürfen höchstens 60° und Positionen im Verlauf höchstens 3 %
der längeren Strecke oder 75 m auseinanderliegen. Geschlossene Runden können
an unterschiedlichen Punkten beginnen. Diese Konstanten sind konservative
Produktentscheidungen, keine aus den Quellen abgeleiteten Genauigkeitsgrenzen.
Die [Implementierung](../../server/app/metrics/route_overlap.py) und ihre
[synthetischen Tests](../../server/tests/test_route_overlap.py) dokumentieren
zusätzlich die Regeln für Lücken, ungültige Geometrie und Mehrfachrunden.

## Vergleichsgruppe und Aussagegrenzen

Die Vergleichsgruppe enthält vollständige, nicht ausgeschlossene Außenläufe aus
derselben dokumentierten Sensorperiode. Sie berücksichtigt den gesamten verfügbaren
passenden Bestand statt nur einer technisch begrenzten Kandidatenliste. Anzahl und
Datumsbereich gehören direkt an die Grafik. Enthält die Gruppe bei einem älteren
ausgewählten Lauf auch spätere Läufe, darf sie nicht „frühere Läufe“ heißen.

Pace wird für alle Läufe einheitlich aus aktiver Dauer und Distanz berechnet. Der
Puls ist der aufgezeichnete Durchschnittspuls, keine auf eine gemeinsame Pace
umgerechnete Größe. Fehlende Messwerte werden nicht ersetzt; gegebenenfalls
unterscheidet sich die Zahl der Beobachtungen pro Kennzahl.

Eine klare Kurzinterpretation wäre „12 s/km schneller · 3 bpm höher als der Median“.
Eine Pace-Verbesserung allein beweist weder bessere Fitness noch einen besser
erfüllten Trainingszweck. Bei gleichem Tempo können weitere Bedingungen den Puls
beeinflussen: Eine kontrollierte Feldstudie mit Läufern zeigte beispielsweise
unterschiedliche Pulsreaktionen bei unterschiedlicher Hydration in Wärme. Daraus
folgt keine allgemeine Wetterkorrekturformel für Milon.
[Casa et al.: Originalstudie](https://pmc.ncbi.nlm.nih.gov/articles/PMC2838466/)

Die Verteilung vermischt bewusst persönliche Trainingsphasen und unterschiedliche
Laufabsichten. Sie ist eine Standortbestimmung innerhalb der beobachteten Läufe,
kein zeitbereinigter Fortschrittstest. Wiederholte Messungen können außerdem
abhängig sein; übliche Unsicherheitsrechnungen für unabhängige Beobachtungen sind
dann ungeeignet. Deshalb keine p-Werte, Signifikanzsterne oder pauschalen
„Fitness besser“-Urteile aus diesem Vergleich.
[NIST: Unsicherheit bei autokorrelierten Messungen](https://www.nist.gov/publications/calculation-uncertainty-mean-autocorrelated-measurements?pub_id=151800)

Ein späterer zusätzlicher Vergleich könnte die vorhandenen gleichmäßigen Minuten
nach Tempo und Steigung paaren. Dabei entsteht **ein Pulsunterschied pro Laufpaar**;
die Anzahl der Minutenpaare darf nicht als Anzahl unabhängiger Läufe ausgegeben
werden. Unterschiedliche Abschnitte und Ermüdungszustände bleiben Einflüsse.
Für die erste kompakte Ansicht reicht die klar beschriftete Rohwert-Verteilung.

## Kompakte Gestaltung

Zwei horizontale Zeilen funktionieren auch auf 375 px: oben jeweils Kennzahl,
ausgewählter Wert und Differenz; darunter die Verteilung über die volle Breite.
Ein Teal-Ring markiert den ausgewählten Lauf, kleine neutrale Punkte die anderen
Läufe, ein kurzer Strich den Median. Eine blasse Quartilsfläche und dünne
Min–Max-Linie ordnen die Punkte ein. Überlagerte Beobachtungen werden nur senkrecht
versetzt; ihre horizontalen Werte bleiben unverändert.

Pace und Puls bekommen eigene beschriftete Skalen mit denselben Schriftgrößen.
Eine gemeinsame Legende genügt. Farbe trägt keine alleinige Bedeutung; Form und
Text unterscheiden die Markierungen. Werte und Differenzen stehen außerhalb der
Grafik, damit sie weder Punkte noch Spannengrenzen überschreiben. Die Methoden
bleiben auf Wunsch aufklappbar, die eigentlichen Ergebnisse immer sichtbar.
