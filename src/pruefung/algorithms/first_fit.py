"""Konstruktive Heuristik: First-Fit über die Studierenden.

Im Unterschied zur Greedy-Baseline (siehe ``pruefung.algorithms.greedy``)
iteriert dieses Verfahren über die *Studierenden* statt über die Sitzplätze:
Für jeden Prüfling wird der erste freie Platz gesucht, der keine harte
Restriktion verletzt. Dazu gehört bei einer Raumvorgabe, dass der Platz im
vorgegebenen Raum liegt.

Der Unterschied wirkt gering, ist aber entscheidend. Die Greedy-Baseline fragt
je Sitzplatz nur den vordersten Prüfling der Warteschlange und überspringt den
Platz endgültig, wenn dieser nicht passt. Ein Konflikt kostet dort also einen
*Sitzplatz*. Hier kostet ein Konflikt lediglich einen Prüfversuch; verbraucht
wird ein Platz nur durch eine tatsächliche Platzierung.

Das Verfahren dient zwei Zwecken: als faire konstruktive Vergleichsgröße und
als Lieferant der Startpopulation für den Genetischen Algorithmus.
"""

from __future__ import annotations

from collections.abc import Iterable

from pruefung.algorithms.greedy import apply_forced_assignments
from pruefung.constraints import seat_conflicts, sort_key
from pruefung.models import ForcedAssignment, SeatingPlan, Student, Venue


def default_order(students: list[Student]) -> list[Student]:
    """Sortierung nach Seminargruppe und anschließend nach Nachname."""
    return sorted(students, key=lambda s: (s.seminar_group, sort_key(s)))


def first_fit_assign(
    students: list[Student],
    venue: Venue,
    forced: list[ForcedAssignment] | None = None,
    order: Iterable[Student] | None = None,
) -> SeatingPlan:
    """Platziert die Studierenden nacheinander auf dem jeweils ersten passenden Platz.

    ``order`` legt die Bearbeitungsreihenfolge fest. Ohne Angabe wird nach
    Seminargruppe und Nachname sortiert; eine zufällige Reihenfolge erzeugt
    unterschiedliche, gleichwertig brauchbare Lösungen -- davon lebt die
    Startpopulation des Genetischen Algorithmus.

    Prüflinge mit Raumvorgabe werden in jeder Reihenfolge zuerst bearbeitet,
    da ihr Wertebereich am kleinsten ist. Untereinander und unter den übrigen
    bleibt die Reihenfolge erhalten. Die Raumvorgabe selbst prüft
    ``seat_conflicts``.
    """
    students_by_id = {s.matriculation_number: s for s in students}
    plan = apply_forced_assignments(forced or [], students_by_id, venue)
    already_placed = set(plan.assignments.values())

    sequence = list(order) if order is not None else default_order(students)
    # Stabile Sortierung: verschiebt nur die Prüflinge mit Raumvorgabe nach vorn.
    sequence.sort(key=lambda s: not s.required_room)
    seats = venue.seats_in_reading_order()

    for student in sequence:
        if student.matriculation_number in already_placed:
            continue
        for seat_id in seats:
            if seat_id in plan.assignments:
                continue
            if not seat_conflicts(seat_id, student, plan, students_by_id, venue):
                plan.assignments[seat_id] = student.matriculation_number
                break
        else:
            plan.unassigned.append(student.matriculation_number)

    return plan
