"""Tests der ersten Stufe: der Verteilung der Studierenden auf die Raeume.

Im Mittelpunkt steht die Reihenfolge der Raeume innerhalb eines Blocks. Sie
entscheidet, welcher Raum welchen Buchstabenbereich erhaelt, und damit
darueber, ob sich eine Einteilung ohne Nennung von Seminargruppen ueberhaupt
finden laesst.
"""

import random

from pruefung.models import Student
from pruefung.room_assignment import (
    build_room_plan,
    candidate_room_plans,
    plan_rule_length,
)
from pruefung.rules import render_rule

# Die Kapazitaeten passen nur zu einer einzigen Raumreihenfolge: Der
# Buchstabenbereich A fasst fuenf Pruefline, B drei und C zwei. Zulaessig ist
# damit allein die Folge R2, R3, R1. Die alphabetische Sortierung der
# Raumnamen, also R1, R2, R3, scheitert.
CAPACITIES = {"R1": 2, "R2": 5, "R3": 3}
DISTRIBUTION = {"A": 5, "B": 3, "C": 2}


def _make_students() -> list[Student]:
    people: list[Student] = []
    number = 100
    for letter, count in DISTRIBUTION.items():
        for run in range(count):
            number += 1
            people.append(
                Student(
                    matriculation_number=str(number),
                    seminar_group=f"G{run % 3 + 1}",
                    name=f"{letter}nachname, Vorname",
                )
            )
    return people


def _all_groups(people: list[Student]) -> set[str]:
    return {s.seminar_group for s in people}


def test_sorted_room_order_alone_cannot_split_this_instance():
    # Dokumentiert den Grund fuer die Suche ueber Raumreihenfolgen: In der
    # alphabetischen Folge der Raumnamen gibt es keine gueltige Aufteilung.
    people = _make_students()
    plan = build_room_plan(
        people, CAPACITIES, [frozenset(_all_groups(people))], [["R1", "R2", "R3"]]
    )
    assert plan is None


def test_a_fitting_room_order_exists():
    people = _make_students()
    plan = build_room_plan(
        people, CAPACITIES, [frozenset(_all_groups(people))], [["R2", "R3", "R1"]]
    )
    assert plan is not None
    assert {current_room: len(v) for current_room, v in plan.rooms.items()} == {
        "R2": 5, "R3": 3, "R1": 2
    }


def test_candidate_search_finds_the_groupless_assignment():
    # Die Suche muss die Reihenfolgen mitdurchlaufen. Andernfalls faellt die
    # gesamte Familie der Einteilungen ohne Gruppennamen aus dem Suchraum und
    # es bleiben nur solche uebrig, die Seminargruppen aufzaehlen muessen.
    people = _make_students()
    covers_all = _all_groups(people)
    plans = list(candidate_room_plans(people, CAPACITIES, random.Random(1)))

    assert plans, "Es wurde ueberhaupt keine Einteilung gefunden."
    short = [p for p in plans if plan_rule_length(p, covers_all) == 0]
    assert short, "Keine Einteilung ohne Nennung von Seminargruppen gefunden."

    # Eine solche Einteilung besteht allein aus Buchstabenbereichen.
    letter_ranges = {render_rule(rule, covers_all) for rule in short[0].rules.values()}
    assert all("G" not in letter_range for letter_range in letter_ranges), letter_ranges


def test_candidate_search_returns_no_duplicates():
    # Verschiedene Blockstrukturen fuehren regelmaessig auf dieselben
    # Einteilungen. Wiederholungen wuerden das Kandidatenbudget der zweiten
    # Stufe fuellen, ohne eine neue Moeglichkeit beizutragen.
    people = _make_students()
    plans = list(candidate_room_plans(people, CAPACITIES, random.Random(1)))
    identifiers = {frozenset(p.rules.items()) for p in plans}
    assert len(identifiers) == len(plans)
