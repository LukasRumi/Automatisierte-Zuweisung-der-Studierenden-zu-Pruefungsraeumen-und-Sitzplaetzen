"""Kennzahlen aus Kapitel 6 der Arbeit, gemessen mit deren Einstellungen.

Die übrigen Tests prüfen, dass jeder Sitzplan zulässig ist. Welche Zahlen die
Arbeit nennt, sichern sie nicht ab. Diese Datei tut das für alle Werte, die
sich in wenigen Sekunden nachrechnen lassen: reale Instanz, keine
Reserveplätze, Nachbarschaftsradius wie in der jeweiligen Tabelle. Ändert ein
Eingriff in den Code eines dieser Ergebnisse, schlägt hier ein Test fehl, und
die Arbeit muss nachgezogen werden.

Die Läufe des Genetischen Algorithmus unter Einteilungsbindung dauern je rund
eine Minute und sind deshalb nicht enthalten.
"""

import statistics
from functools import lru_cache
from pathlib import Path

import pytest

from pruefung.algorithms.genetic import GAConfig
from pruefung.parsing.students import parse_students_csv
from pruefung.pipeline import assign
from pruefung.preprocessing import preprocess_students
from pruefung.venue import load_venue

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "pruefung1"


@lru_cache(maxsize=None)
def _instance(radius: float):
    students, forced = parse_students_csv(EXAMPLES / "teilnehmer.csv")
    venue = load_venue(EXAMPLES / "rooms", neighbor_radius=radius, reserve_seats=0)
    return preprocess_students(students), venue, forced


def _placed(radius: float = 2.65, **options) -> tuple[int, dict]:
    """Platzierte reguläre Prüflinge, also ohne den NTA-Raum."""
    students, venue, forced = _instance(radius)
    result = assign(students, venue, forced, **options)
    regular = len(result.plan.assignments) - result.metrics["nta_zugewiesen"]
    return regular, result.metrics


@pytest.mark.parametrize(
    "radius,variant_a,variant_b",
    [(1.45, 84, 135), (2.10, 76, 133), (2.65, 65, 135)],
)
def test_table_radius_constructive_variants(radius, variant_a, variant_b):
    # Tabelle tab:radius, Spalten Variante A und B.
    assert _placed(radius, algorithm="greedy")[0] == variant_a
    assert _placed(radius, algorithm="first-fit")[0] == variant_b


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ga_seats_everyone_without_needing_the_repair(seed):
    # Tabelle tab:radius (GA 135/135) und tab:startpopulation (|V| = 0 bei
    # konstruktivem Anteil): Das beste Individuum ist am Ende der Evolution
    # bereits zulässig.
    placed, metrics = _placed(algorithm="genetic", ga_config=GAConfig(seed=seed))
    assert placed == 135
    assert metrics["kostenverlauf"][-1][0] == 0


def test_variant_a_under_rule_binding():
    # Tabelle tab:verfahren-bindung, Zeile Variante A: 75 mit L = 0, und die
    # gruppenfreie Einteilung aus Abbildung fig:raumreihenfolge.
    placed, metrics = _placed(algorithm="greedy", room_assignment="rules")
    assert placed == 75
    assert metrics["regellaenge"] == 0
    assert metrics["regeln"] == {"TR129": "A-F", "TRA140": "G-O", "FE006": "P-Z"}


def test_variant_a_under_soft_rule_binding():
    # Tabelle tab:verfahren-bindung, Zeile Variante A unter rules-soft: Median
    # 133, und die Saat 1 liegt auf dem Median.
    placed, metrics = _placed(algorithm="greedy", room_assignment="rules-soft", rule_seed=1)
    assert placed == 133
    assert metrics["regellaenge"] == 0


def test_variant_b_under_rule_binding_median_over_ten_seeds():
    # Tabelle tab:verfahren-bindung, Zeile Variante B: Median 123 bei L = 6
    # unter harter, Median 134 unter weicher Bindung.
    hard = [_placed(algorithm="first-fit", room_assignment="rules", rule_seed=s)
            for s in range(1, 11)]
    soft = [_placed(algorithm="first-fit", room_assignment="rules-soft", rule_seed=s)
            for s in range(1, 11)]
    assert statistics.median(p for p, _ in hard) == 123
    assert statistics.median(m["regellaenge"] for _, m in hard) == 6
    assert statistics.median(p for p, _ in soft) == 134
