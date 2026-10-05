# Nächste Schritte für Körperfortschritt und Coach

Stand: 2026-10-05. Die folgenden Überlegungen dokumentieren die ursprüngliche
Recherche. Gemeinsamer Körpervergleich (Punkt 1) und Wochenmaßnahmen sind inzwischen
umgesetzt; Versuchspläne und weitere Vorschläge bleiben offen. Grundlage sind Code und Primärquellen; persönliche
Messdaten wurden für diese Recherche weder gelesen noch an Suchdienste gesendet.

## Was bereits vorhanden ist

Milon hat Umfangskurven mit festen Messstellen und historischen Einträgen,
Gewichtsverläufe, Kraftindex, eine Wochenbilanz, freiwillige Energie-Check-ins und
beschreibende Zusammenhänge zwischen Erholung und Leistung. Der Coach kennt Ziele
und soll schon heute genau eine Wochenmaßnahme nennen. Diese Funktionen erneut
als neue Karten anzubieten würde wenig gewinnen. Geprüft wurden insbesondere
`client/components/{BodyCircumferences,WeeklyReview,CheckIn,GarminRecovery}.tsx`
und `server/app/{circumferences,checkins,metrics/recovery_analysis,coach/prompts,coach/profile}.py`.

## 1. Körperfortschritt gemeinsam einordnen

**Frage:** „Werde ich am Bauch schlanker, während meine Leistung erhalten bleibt?“

Neu wäre eine gemeinsame Einordnung der vorhandenen Reihen über denselben
Zeitraum, beispielsweise vier oder acht Wochen: ein gewähltes Bauchmaß,
Gewichtsmittel und vergleichbare Kraftleistungen. Drei kleine Zeilen mit Delta,
Messzeitraum und Abdeckung reichen. Beispieltext ohne erfundene Zahlen:
„Bauchumfang sinkt, Gewicht sinkt, Kraftleistung bleibt ungefähr stabil.“
Die getrennten Kurven bleiben zur Prüfung erreichbar.

Die Forschungsrichtung passt: Eine randomisierte Studie mit 24 Wochen Training
und MRT-Messungen fand, dass ausreichend große Gewichts- oder Taillenumfangsänderungen
oft mit Veränderungen abdominalen Fettgewebes einhergingen. Das validiert weder
eine Prozentformel für Milon noch jede einzelne kleine Umfangsänderung.
[Brennan et al., 2020: Individual Response to Standardized Exercise: Total and Abdominal Adipose Tissue](https://pubmed.ncbi.nlm.nih.gov/31479006/)

**Verfügbar:** Gewicht, standardisierte manuelle Umfänge, Hevy-Sätze und
Übungsidentitäten. **Noch nötig:** genügend wiederholte Umfangsmessungen und eine
festgelegte Vergleichsauswahl für Kraft. Messstelle und Protokoll müssen gleich
bleiben; Bauch auf Nabelhöhe und schmalste Taille werden nicht vermischt.
Vier bis acht Wochen wären eine Produktentscheidung, keine validierte
Nachweisgrenze. Messlücken und unvereinbare Übungswechsel bleiben sichtbar.

**Grenze:** Kraft ist ein Leistungsindikator und kein Beweis für erhaltene oder
gewachsene Muskelmasse. Eine randomisierte Trainingsstudie zeigte unterschiedliche
Kraftzuwächse bei ähnlicher Hypertrophie, mit Unterschieden in neuronaler Anpassung.
Deshalb kein „Muskel erhalten“-Siegel und kein synthetischer Körperfettwert.
[Jenkins et al., Originalstudie, 2017](https://pubmed.ncbi.nlm.nih.gov/28611677/)

## 2. Ein persönliches Alltagsexperiment

**Frage:** „Hilft diese eine Änderung tatsächlich in meinem Alltag?“

Neu wäre eine vorher festgelegte Frage mit Start, Dauer und genau einem primären
Ergebnis, statt nachträglich zahlreiche Korrelationen zu durchsuchen. Denkbares
Beispiel: eine selbst gewählte frühere Koffein-Grenze und die folgende Schlafdauer.
Die Plausibilität ist durch eine placebokontrollierte Studie zur Schlafstörung
nach 400 mg Koffein gestützt; deren hohe Einzeldosis liefert keine universelle
Uhrzeit oder individuelle Wirkungsgröße.
[Drake et al., Originalstudie, 2013](https://pubmed.ncbi.nlm.nih.gov/24235903/)

**Verfügbar:** Schlafnächte, Training und freiwillige Tagesenergie.
**Noch nötig:** gewählte Änderung, dokumentierte Phasen und ein freiwilliges
„heute umgesetzt“; Kaffeezeit/-menge lassen sich nicht aus Garmin ableiten.
UI: eine kleine laufende Karte, ein Antippen zur Umsetzung, danach ein
Phasenvergleich mit tatsächlichen Nächten und Ausfällen. Der normale Check-in
bleibt unverändert einfach.

**Grenze:** Ein Vorher-nachher-Vergleich ist zunächst Selbstbeobachtung. Für einen
stärkeren individuellen Test wären wiederholte, möglichst vorab randomisierte
Vergleichsphasen sowie Beachtung von Nachwirkungen nötig. Das entspricht dem
Kern von N-of-1-Studien; es eignet sich besonders für rasch einsetzende und
reversible Effekte. Langfristiger Fettabbau ist kein passender kurzer ABAB-Test.
[CENT 2015, Originalleitlinie](https://www.bmj.com/content/350/bmj.h1738)
Ohne entsprechendes Design lautet das Ergebnis „beobachteter Unterschied“, nicht
„bewiesene Ursache“. Es gibt keine feste Zahl an Tagen, die automatisch Beweiskraft schafft.

## 3. Die Wochenentscheidung weiterverfolgen

**Frage:** „Was nehme ich aus dieser Woche mit – und was wurde aus dem letzten Vorschlag?“

Die Wochenbilanz und die einzelne Coach-Empfehlung existieren bereits. Neu wäre
das Verknüpfen einer vom Nutzer übernommenen Maßnahme mit ihrem späteren
Rückblick: „umgesetzt / teilweise / nicht ausprobiert“, dazu die Entwicklung des
vorher gewählten Zielwerts. Der nächste Bericht kann dann begründet „beibehalten“,
„anpassen“ oder „noch Daten sammeln“ vorschlagen. Eine untergeordnete Zeile unter
der bestehenden Wochenbilanz genügt; keine zusätzliche Seite nötig.

**Verfügbar:** Coach-Ziele und Prioritäten, gespeicherte Reports, datierte
Wochenkennzahlen, Energie-Check-ins und Garmin-Erholung. **Noch nötig:** ein
strukturierter Maßnahmen-Datensatz mit Annahme durch den Nutzer, Zeitfenster,
Zielwert und optionaler Rückmeldung. Freier Reporttext allein ist kein belastbarer
Status. Die objektiven Zahlen berechnet weiterhin Milon; der Coach formuliert
kurz die Einordnung. Dies ist ein Produktvorschlag, keine klinisch validierte Intervention.

Erholungswerte liefern Kontext, werden aber nicht zu einem weiteren Gesamtwert
aufsummiert: Garmins Trainingsbereitschaft enthält bereits Schlaf, HRV,
Erholungszeit, Belastung und Stress. Mehrere dieser Anzeigen sind daher keine
unabhängigen Bestätigungen. Das ist eine Folgerung aus der dokumentierten
Zusammensetzung. [Garmin: Training Readiness](https://www.garmin.com/en-XD/garmin-technology/running-science/physiological-measurements/training-readiness/)

**Reihenfolge:** zuerst die gemeinsame Körper-Einordnung, dann das Weiterverfolgen
einer Wochenmaßnahme; persönliche Experimente als freiwillige spätere Erweiterung.
Alle drei Vorschläge verwenden die vorhandenen klinischen Karten, Typografie und
Farben. Die zusätzliche Information soll Entscheidungen vereinfachen und ersetzt
keine Messung durch einen scheinbar präzisen Score.
