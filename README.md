# Prüfungsraumzuweisung

Kommandozeilenwerkzeug, das Studierende automatisch auf Prüfungsräume und Sitzplätze verteilt. Es ist im Rahmen der Bachelorarbeit „Automatisierte Zuweisung von Studierenden zu Prüfungsräumen und Sitzplätzen“ (Lukas Ruminski, HTWK Leipzig, 2026) entstanden.

Das Werkzeug hält folgende Regeln immer ein:

* Angehörige derselben Seminargruppe sitzen nicht nebeneinander, auch nicht schräg oder direkt davor und dahinter.
* Prüflinge mit Nachteilsausgleich (NTA) sitzen in einem eigenen Raum, und dort sitzt sonst niemand.
* Der öffentliche Aushang zeigt keine Namen, sondern nur die letzten Ziffern der Matrikelnummer. Diese sind je Raum eindeutig.
* Feste Plätze und Raumvorgaben für einzelne Prüflinge werden übernommen.

Darüber hinaus versucht es, Gruppen in wenigen Räumen zu halten, die Plätze alphabetisch zu ordnen und keine Lücken zu lassen. Auf Wunsch lässt sich die Verteilung auf die Räume als kurze Einteilung aushängen, etwa „A-F in TR129“.

## Voraussetzungen

* Python 3.11 oder neuer
* sonst nichts. Auch die PDF-Dateien erzeugt das Werkzeug ohne Zusatzbibliothek.
* Nur für die Tests: `pytest`

## Installation

Im Ordner dieses Repositorys:

```bash
python -m pip install -e .
```

Danach steht der Befehl `pruefung` zur Verfügung. Gleichwertig ist `python -m pruefung`.

Ohne Installation geht es auch. Dann muss der Ordner `src` im Suchpfad liegen, unter Windows (PowerShell) etwa mit `$env:PYTHONPATH="src"`, unter Linux und macOS mit `export PYTHONPATH=src`.

## Schnellstart

```bash
python -m pruefung assign --students examples/pruefung1/teilnehmer.csv --rooms examples/pruefung1/rooms --output out --room-assignment rules-soft --seed 42
```

Der Lauf dauert gut eine Minute. Danach meldet das Werkzeug unter anderem, wie viele Prüflinge einen Platz bekommen haben und welche Einteilung je Raum gilt:

```
Zugewiesen: 139/139
Aushangplan zeigt 4 Endziffern der Matrikelnummer
Raumzuordnung: rules-soft (10 Ausnahmen, auf den Aushängen 10 Einträge)
   FE006: P-Z
   TR129: A-F
   TRA140: G-O
NTA: 4 Studierende in Raum NTA
```

Die fertigen Pläne liegen dann im Ordner `out`. Ohne `--seed` kann das Ergebnis von Lauf zu Lauf leicht abweichen.

## Anleitung für eine Prüfung

### 1. Teilnehmerliste vorbereiten

Eine CSV-Datei, eine Zeile je Prüfling, getrennt durch Semikolon. Die Spalten sind Matrikelnummer, Seminargruppe, Name (`Nachname, Vorname`) und ein Vermerk. Eine Kopfzeile ist nicht nötig. Die Matrikelnummern in diesen Beispielen sind ausgedacht:

```
847891;25INB-1;Albrecht, Anna;
853261;25INB-2;Baumann, Ben;NTA
848351;25INB-1;Conrad, Clara;FE006
848352;25INB-3;Dietrich, David;FE006:A1
```

Der Vermerk in der letzten Spalte bedeutet:

| Vermerk | Wirkung |
| --- | --- |
| leer | keine Vorgabe |
| `NTA` | Nachteilsausgleich, der Prüfling sitzt im NTA-Raum |
| `FE006` (ein Raumname) | Raumvorgabe, den Platz wählt das Werkzeug |
| `FE006:A1` | fester Platz |
| anderer Text | bleibt ohne Wirkung, das Werkzeug weist nach dem Lauf darauf hin |

Groß- und Kleinschreibung spielt keine Rolle. Alternativ geht auch ein Format mit Kopfzeile und Komma als Trenner, mit den Spalten `matrikelnummer`, `seminargruppe`, `name` und `nachteilsausgleich` (siehe `examples/students.csv`).

Widersprüchliche Vorgaben weist das Werkzeug vor dem Lauf zurück, etwa einen unbekannten Raum, den NTA-Raum für jemanden ohne Nachteilsausgleich oder mehr Vorgaben, als ein Raum Plätze hat.

### 2. Räume zeichnen

Je Raum eine Textdatei in einem gemeinsamen Ordner. Der Dateiname ist der Raumname, also `FE006.txt` für den Raum FE006. Jede Zeile ist eine Sitzreihe, die Tafel ist oben.

| Zeichen | Bedeutung |
| --- | --- |
| `X` | Sitz, der belegt werden darf |
| `.` | Sitz, der leer bleibt |
| `_` | kein Sitz |
| Leerzeichen | Gang |
| `<` | Leerraum mit halber Sitzbreite, für versetzte Reihen |

Beispiel mit einer freien Reihe und einer um eine halbe Sitzbreite versetzten Reihe:

```
X.X.X.X.X.X.X
.............
<X.X.X.X.X.X.
```

Ein Raum für Nachteilsausgleiche heißt `NTA` oder endet auf `_nta` bzw. `-nta`. Alternativ lässt er sich mit `--nta-room` benennen.

### 3. Zuweisung starten

```bash
pruefung assign --students teilnehmer.csv --rooms raeume --output ergebnis --room-assignment rules-soft
```

Welche Raumzuordnung passt, hängt davon ab, was ausgehängt werden soll:

| `--room-assignment` | Ergebnis | Laufzeit |
| --- | --- | --- |
| `free` (Standard) | alle Räume frei genutzt, die Verteilung lässt sich aber nicht kurz aushängen | wenige Sekunden |
| `rules` | Verteilung genau nach Einteilung (`A-F in TR129`), dafür bleiben eher Prüflinge ohne Platz | gut eine Minute |
| `rules-soft` | wie `rules`, einzelne Prüflinge dürfen abweichen und stehen mit ihrem Code auf dem Aushang | gut eine Minute |

Für den Einsatz empfiehlt sich `rules-soft`. Auf der Beispielprüfung bekommen damit in der Regel alle einen Platz, und die Einteilung nennt keine einzige Seminargruppe.

### 4. Ergebnis prüfen

Die wichtigste Zeile ist `Zugewiesen: x/y`. Bleiben Prüflinge ohne Platz, meldet das Werkzeug das mit `WARNUNG` und nennt die Betroffenen in `report.json`. Dann helfen ein zusätzlicher Raum, `rules-soft` statt `rules` oder `free`. Ebenso meldet es jede Verletzung einer Regel, was bei korrekten Eingaben nicht vorkommen sollte.

### 5. Drucken

| Datei | Zweck |
| --- | --- |
| `aushaenge.pdf` | alles für die Türen: je Raum die Raumzuordnung und dahinter der Aushangplan |
| `sitzplatzzuordnung.pdf` | alles für die Aufsicht: Sitzplan je Raum mit Namen, dahinter die alphabetische Gesamtliste |
| `raumzuordnung.pdf` | die Einteilung aller Räume auf einer Seite, etwa zum Versand mit der Einladung |

Daneben liegen dieselben Inhalte einzeln je Raum (`plan_<Raum>`, `aufsicht_<Raum>`, `uebersichtsplan`), jeweils als PDF und als Text. `report.json` enthält Laufzeit, Kosten der weichen Ziele und die Nachweise, dass alle Regeln eingehalten sind.

Nur `aushaenge.pdf`, `plan_<Raum>` und `raumzuordnung.pdf` sind für die Öffentlichkeit gedacht. Alle anderen Dateien enthalten Namen und volle Matrikelnummern.

## Alle Optionen

| Option | Standard | Bedeutung |
| --- | --- | --- |
| `--students` | | Teilnehmerliste (CSV) |
| `--rooms` | | Ordner mit den Raumdateien |
| `--output` | | Ausgabeordner |
| `--room-assignment` | `free` | `free`, `rules` oder `rules-soft` (siehe oben) |
| `--max-exceptions` | keine Grenze | höchstens so viele Abweichungen bei `rules-soft` |
| `--rule-candidates` | 24 | so viele Einteilungen werden durchgerechnet. Weniger geht schneller |
| `--algorithm` | `genetic` | `genetic` (Genetischer Algorithmus), `first-fit` oder `greedy` (beide konstruktiv, sehr schnell) |
| `--reserve-seats` | 1 | Plätze je Raum, die frei bleiben, etwa für einen defekten Stuhl |
| `--neighbor-radius` | 2.65 | ab welchem Abstand zwei Plätze nicht mehr benachbart sind, gemessen in Sitzbreiten |
| `--code-digits` | automatisch | Zahl der Endziffern auf dem Aushang. Automatisch heißt: kleinster brauchbarer Wert aus 2, 3 oder 4 |
| `--nta-room` | automatisch | Name des NTA-Raumes |
| `--seed` | zufällig | feste Zufallssaat, damit ein Lauf wiederholbar ist |
| `--format` | `both` | `pdf`, `text` oder `both` |
| `--quiet` | | keine Zusammenfassung auf dem Bildschirm |
| `--population`, `--generations`, `--mutation-rate`, `--patience` | 100, 200, 0.05, 40 | Einstellungen des Genetischen Algorithmus |
| `--w-fragmentation`, `--w-sorting`, `--w-gaps` | 1, 0.01, 1 | Gewichte der weichen Ziele |

## Beispieldaten

* `examples/pruefung1/`: die Prüfung aus der Arbeit mit 139 Prüflingen aus 23 Seminargruppen in drei Räumen und einem NTA-Raum. `raumnotation.txt` erklärt die Zeichen der Raumdateien. Die Liste ist anonymisiert:
  * Die Namen waren schon in der Originalliste anonymisiert und sind unverändert übernommen.
  * Die Matrikelnummern sind durch ausgedachte neunstellige Nummern ersetzt. Ihre Reihenfolge bleibt dabei gleich, und zwei Nummern stimmen in den letzten Ziffern genau dann überein, wenn es die echten auch tun. Das Werkzeug liefert deshalb dieselben Sitzpläne wie mit der Originalliste.
* `examples/students.csv` mit `examples/rooms/`: eine kleine ausgedachte Prüfung mit 24 Prüflingen in zwei Räumen, die vor allem die Tests nutzen.

## Tests

```bash
python -m pip install pytest
python -m pytest
```

Der vollständige Durchlauf dauert etwa zwei Minuten. `tests/test_kennzahlen.py` rechnet dabei die schnell nachprüfbaren Zahlen aus Kapitel 6 der Arbeit nach.

## Aufbau des Quelltexts

| Modul | Inhalt |
| --- | --- |
| `cli.py` | Kommandozeile |
| `parsing/` | Einlesen von Teilnehmerliste und Raumdateien |
| `venue.py`, `constraints.py` | Räume, Nachbarschaft, Regeln und Zielfunktion |
| `pipeline.py`, `room_assignment.py`, `rules.py` | Ablauf, Verteilung auf die Räume und Einteilungen |
| `algorithms/` | die drei Verfahren der Sitzplatzvergabe |
| `nta.py`, `requirements.py`, `preprocessing.py` | Nachteilsausgleiche, Vorgaben, Anzeigecodes |
| `output/` | Aushänge, Aufsichtspläne, Report und PDF-Erzeugung |
| `instances.py` | Erzeugung synthetischer Prüfungen für Messungen |

Wie die Verfahren arbeiten und warum sie so entworfen sind, beschreibt die Bachelorarbeit.
