from pathlib import Path

from pruefung.algorithms.greedy import greedy_assign
from pruefung.constraints import compute_neighbors, find_hard_violations
from pruefung.models import ForcedAssignment, Student, Venue
from pruefung.parsing.rooms import parse_room_grid
from pruefung.parsing.students import parse_students_csv
from pruefung.preprocessing import preprocess_students

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _venue(grid, radius=1.45):
    """Expliziter Radius: die Aussagen dieser Tests beziehen sich auf eine
    Nachbarschaft aus ausschließlich direkt angrenzenden Plätzen."""
    room, seats = parse_room_grid("R", grid)
    return Venue(rooms={"R": room}, seats=seats, neighbors=compute_neighbors(seats, radius=radius))


def test_greedy_never_violates_group_separation_even_when_seats_remain_empty():
    # Vier gegenseitig verkettete Plätze (A1-A2-A3-A4), eine einzige Gruppe:
    # die maximale konfliktfreie Belegung ist eine unabhängige Menge der Größe 2.
    venue = _venue(["XXXX"])
    students = [
        Student(matriculation_number=str(i), seminar_group="G1")
        for i in range(4)
    ]
    plan = greedy_assign(students, venue)
    students_by_id = {s.matriculation_number: s for s in students}
    assert find_hard_violations(plan, venue, students_by_id) == []
    assert len(plan.assignments) + len(plan.unassigned) == len(students)
    assert len(plan.unassigned) == 2


def test_greedy_can_get_stuck_in_a_local_optimum():
    # Bekannte Schwäche der Baseline-Heuristik (Abschnitt 4.5 der Arbeit): einmal
    # übersprungene Plätze werden nie erneut geprüft. Platz R:A2 bliebe hier
    # leer, obwohl er für Gruppe G2 konfliktfrei gewesen wäre.
    venue = _venue(["XXXX"])
    students = [
        Student(matriculation_number="a", seminar_group="G1"),
        Student(matriculation_number="b", seminar_group="G1"),
        Student(matriculation_number="c", seminar_group="G2"),
        Student(matriculation_number="d", seminar_group="G2"),
    ]
    plan = greedy_assign(students, venue)
    assert plan.unassigned == ["d"]
    assert "R:A2" not in plan.assignments


def test_greedy_leaves_students_unassigned_when_infeasible():
    # Nur zwei benachbarte Plätze, aber drei Studierende derselben Gruppe:
    # höchstens einer der drei kann konfliktfrei sitzen.
    venue = _venue(["XX"])
    students = [
        Student(matriculation_number=str(i), seminar_group="G1")
        for i in range(3)
    ]
    plan = greedy_assign(students, venue)
    assert len(plan.unassigned) == 2
    students_by_id = {s.matriculation_number: s for s in students}
    assert find_hard_violations(plan, venue, students_by_id) == []


def test_forced_assignment_is_respected():
    venue = _venue(["XX"])
    students = [
        Student(matriculation_number="1", seminar_group="G1"),
        Student(matriculation_number="2", seminar_group="G2"),
    ]
    forced = [ForcedAssignment(matriculation_number="2", room="R", seat_label="A2")]
    plan = greedy_assign(students, venue, forced)
    assert plan.assignments["R:A2"] == "2"


def test_full_example_pipeline_never_violates_hard_constraints():
    students, forced = parse_students_csv(EXAMPLES / "students.csv")
    students = preprocess_students(students)

    from pruefung.venue import load_venue

    venue = load_venue(EXAMPLES / "rooms")
    plan = greedy_assign(students, venue, forced)

    students_by_id = {s.matriculation_number: s for s in students}
    assert find_hard_violations(plan, venue, students_by_id) == []
    assert len(plan.assignments) + len(plan.unassigned) == len(students)
    # Nachteilsausgleich: Student 4500011 muss auf SR1:A1 sitzen.
    assert plan.assignments["SR1:A1"] == "4500011"
