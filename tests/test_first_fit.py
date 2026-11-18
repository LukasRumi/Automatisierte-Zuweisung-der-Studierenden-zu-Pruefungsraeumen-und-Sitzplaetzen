from pruefung.algorithms.first_fit import first_fit_assign
from pruefung.algorithms.greedy import greedy_assign
from pruefung.constraints import compute_neighbors, find_all_violations
from pruefung.models import ForcedAssignment, Student, Venue
from pruefung.parsing.rooms import parse_room_grid


def _venue(grid, radius=1.45):
    room, seats = parse_room_grid("R", grid)
    return Venue(rooms={"R": room}, seats=seats, neighbors=compute_neighbors(seats, radius=radius))


def _students(count, group_names):
    return [
        Student(
            matriculation_number=str(1000 + i),
            seminar_group=group_names[i % len(group_names)],
        )
        for i in range(count)
    ]


def test_first_fit_respects_the_hard_constraints():
    venue = _venue(["XXXX", "XXXX"])
    students = _students(6, ["G1", "G2"])
    plan = first_fit_assign(students, venue)
    by_id = {s.matriculation_number: s for s in students}
    assert find_all_violations(plan, venue, by_id) == []


def test_first_fit_does_not_lose_seats_on_conflicts():
    # Kernunterschied zur Greedy-Baseline: Diese prüft je Platz nur den
    # vordersten Prüfling und verliert den Platz bei einem Konflikt endgültig.
    # First-Fit verbraucht einen Platz nur durch eine echte Platzierung.
    venue = _venue(["XXXX"])
    students = [
        Student(matriculation_number="a", seminar_group="G1"),
        Student(matriculation_number="b", seminar_group="G1"),
        Student(matriculation_number="c", seminar_group="G2"),
        Student(matriculation_number="d", seminar_group="G2"),
    ]
    greedy = greedy_assign(students, venue)
    first_fit = first_fit_assign(students, venue)

    assert len(greedy.assignments) == 3  # R:A2 bleibt ungenutzt
    assert len(first_fit.assignments) == 4
    by_id = {s.matriculation_number: s for s in students}
    assert find_all_violations(first_fit, venue, by_id) == []


def test_first_fit_respects_forced_assignments():
    venue = _venue(["XX"])
    students = [
        Student(matriculation_number="1", seminar_group="G1"),
        Student(matriculation_number="2", seminar_group="G2"),
    ]
    forced = [ForcedAssignment(matriculation_number="2", room="R", seat_label="A2")]
    plan = first_fit_assign(students, venue, forced)
    assert plan.assignments["R:A2"] == "2"
    assert len(plan.assignments) == 2


def test_order_changes_the_result_but_not_its_validity():
    venue = _venue(["XXXX", "XXXX"])
    students = _students(6, ["G1", "G2", "G3"])
    by_id = {s.matriculation_number: s for s in students}

    forwards = first_fit_assign(students, venue, order=students)
    backwards = first_fit_assign(students, venue, order=list(reversed(students)))

    assert find_all_violations(forwards, venue, by_id) == []
    assert find_all_violations(backwards, venue, by_id) == []
    # Unterschiedliche Reihenfolgen liefern unterschiedliche, gleichwertig
    # gültige Lösungen -- davon lebt die Startpopulation des GA.
    assert forwards.assignments != backwards.assignments
