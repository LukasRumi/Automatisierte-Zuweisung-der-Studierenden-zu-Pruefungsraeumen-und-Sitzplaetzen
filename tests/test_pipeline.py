from pathlib import Path

import pytest

from pruefung.algorithms.genetic import GAConfig
from pruefung.constraints import compute_neighbors, find_code_violations, find_hard_violations
from pruefung.models import Student, Venue
from pruefung.nta import find_nta_violations
from pruefung.parsing.rooms import parse_room_grid
from pruefung.parsing.students import parse_students_csv
from pruefung.pipeline import assign
from pruefung.preprocessing import preprocess_students
from pruefung.venue import load_venue

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _venue(grids: dict[str, list[str]]) -> Venue:
    rooms = {}
    seats = {}
    for name, grid in grids.items():
        room, room_seats = parse_room_grid(name, grid)
        rooms[name] = room
        seats.update(room_seats)
    return Venue(rooms=rooms, seats=seats, neighbors=compute_neighbors(seats))


def _student(matriculation_number: str, group: str, accommodation: str = "") -> Student:
    return Student(
        matriculation_number=matriculation_number,
        seminar_group=group,
        accommodation=accommodation,
    )


def test_nta_room_is_exclusive_in_both_directions():
    venue = _venue({"HS5": ["XX", "XX"], "NTA": ["XX", "XX"]})
    students = [
        _student("11", "G1", "NTA"),
        _student("22", "G2"),
        _student("33", "G3"),
    ]

    result = assign(students, venue, algorithm="greedy")
    students_by_id = {s.matriculation_number: s for s in students}

    assert result.nta_rooms == ["NTA"]
    assert find_nta_violations(result.plan, venue, students_by_id, result.nta_rooms) == []
    assert find_hard_violations(result.plan, venue, students_by_id) == []
    # NTA-Studierender im NTA-Raum, alle anderen außerhalb.
    assert venue.seats[result.plan.seat_of("11")].room == "NTA"
    assert venue.seats[result.plan.seat_of("22")].room == "HS5"
    assert venue.seats[result.plan.seat_of("33")].room == "HS5"


def test_nta_students_are_seated_from_the_front():
    # Drei Reihen; die NTA-Belegung muss in der vordersten Reihe beginnen.
    venue = _venue({"NTA": ["XX", "XX", "XX"], "HS5": ["XX"]})
    students = [_student("11", "G1", "NTA"), _student("22", "G2", "NTA")]

    result = assign(students, venue, algorithm="greedy")
    occupied_rows = {venue.seats[seat_id].row for seat_id in result.plan.assignments}
    assert occupied_rows == {0}


def test_nta_students_without_nta_room_raise_an_error():
    venue = _venue({"HS5": ["XX"]})
    students = [_student("11", "G1", "NTA")]
    with pytest.raises(ValueError, match="NTA"):
        assign(students, venue, algorithm="greedy")


def test_students_with_the_same_display_code_land_in_different_rooms():
    # 730081 und 780081 werden bei drei Stellen beide zu "081" und dürfen nicht in denselben Raum.
    venue = _venue({"A": ["XX"], "B": ["XX"]})
    students = preprocess_students(
        [
            Student(matriculation_number="730081", seminar_group="G1"),
            Student(matriculation_number="780081", seminar_group="G2"),
        ]
    )

    result = assign(students, venue, algorithm="greedy", code_length=3)
    students_by_id = {s.matriculation_number: s for s in result.students}

    assert find_code_violations(result.plan, venue, students_by_id) == []
    room_ids = {venue.seats[seat].room for seat in result.plan.assignments}
    assert len(result.plan.assignments) == 2
    assert room_ids == {"A", "B"}


def test_code_length_is_raised_automatically_when_two_digits_do_not_suffice():
    # Bei zwei Stellen beide "81", bei drei Stellen mit "081" und "181" eindeutig.
    # Da nur ein Raum zur Verfügung steht, muss auf drei Stellen ausgewichen werden.
    venue = _venue({"A": ["XX"]})
    students = preprocess_students(
        [
            Student(matriculation_number="730081", seminar_group="G1"),
            Student(matriculation_number="730181", seminar_group="G2"),
        ]
    )
    result = assign(students, venue, algorithm="greedy")

    assert result.code_length == 3
    assert {s.display_code for s in result.students} == {"081", "181"}
    assert len(result.plan.assignments) == 2


def test_rule_based_room_assignment_is_fully_describable():
    students, forced = parse_students_csv(EXAMPLES / "pruefung1" / "teilnehmer.csv")
    students = preprocess_students(students)
    venue = load_venue(EXAMPLES / "pruefung1" / "rooms")

    result = assign(
        students,
        venue,
        forced,
        algorithm="greedy",
        room_assignment="rules",
        rule_candidates=2,
    )

    # Der harte Modus lässt per Definition keine Ausnahme zu.
    assert result.metrics["ausnahmen"] == 0
    # Für jeden belegten regulären Raum liegt eine formulierte Regel vor.
    assert result.metrics["regeln"]
    by_id = {s.matriculation_number: s for s in result.students}
    assert find_hard_violations(result.plan, venue, by_id) == []
    assert find_code_violations(result.plan, venue, by_id) == []


def test_rules_stay_short_enough_to_be_posted():
    # Eine ausnahmefreie Regel ist wertlos, wenn sie dreizehn Seminargruppen
    # einzeln benennt. Die praefixweise Blockbildung haelt Geschwistergruppen
    # zusammen, sodass sie sich zusammenfassen lassen. Welche Struktur am Ende
    # gewinnt, haengt von der Instanz ab, kurz muss sie in jedem Fall bleiben.
    students, forced = parse_students_csv(EXAMPLES / "pruefung1" / "teilnehmer.csv")
    students = preprocess_students(students)
    venue = load_venue(EXAMPLES / "pruefung1" / "rooms")

    result = assign(
        students, venue, forced, algorithm="first-fit", room_assignment="rules"
    )

    assert result.metrics["ausnahmen"] == 0
    assert result.metrics["regellaenge"] <= 8


def test_soft_mode_seats_more_students_than_the_hard_mode():
    students, forced = parse_students_csv(EXAMPLES / "pruefung1" / "teilnehmer.csv")
    students = preprocess_students(students)
    venue = load_venue(EXAMPLES / "pruefung1" / "rooms")

    shared = dict(algorithm="greedy", rule_candidates=2)
    hard = assign(students, venue, forced, room_assignment="rules", **shared)
    soft = assign(students, venue, forced, room_assignment="rules-soft", **shared)

    assert len(soft.plan.assignments) >= len(hard.plan.assignments)
    # Die zusätzlichen Plätze werden mit Ausnahmen erkauft.
    if len(soft.plan.assignments) > len(hard.plan.assignments):
        assert soft.metrics["ausnahmen"] > hard.metrics["ausnahmen"]


def test_first_fit_is_selectable_as_an_algorithm():
    venue = _venue({"A": ["XXXX", "XXXX"]})
    students = preprocess_students(
        [
            Student(matriculation_number=f"{830000 + i}1", seminar_group=f"G{i % 2}",
                    name=f"N{i}, V")
            for i in range(5)
        ]
    )
    result = assign(students, venue, algorithm="first-fit")
    by_id = {s.matriculation_number: s for s in result.students}
    assert find_hard_violations(result.plan, venue, by_id) == []
    assert find_code_violations(result.plan, venue, by_id) == []
    # Die studierendengetriebene Variante verliert keine Plaetze an Konflikte.
    greedy = assign(students, venue, algorithm="greedy")
    assert len(result.plan.assignments) >= len(greedy.plan.assignments)


def test_unknown_algorithm_is_rejected():
    venue = _venue({"A": ["XX"]})
    with pytest.raises(ValueError, match="Algorithmus"):
        assign([], venue, algorithm="quatsch")


def test_unknown_room_assignment_mode_is_rejected():
    venue = _venue({"A": ["XX"]})
    with pytest.raises(ValueError, match="Raumzuordnung"):
        assign([], venue, algorithm="greedy", room_assignment="quatsch")


def test_real_example_data_is_feasible_with_both_algorithms():
    students, forced = parse_students_csv(EXAMPLES / "pruefung1" / "teilnehmer.csv")
    students = preprocess_students(students)
    venue = load_venue(EXAMPLES / "pruefung1" / "rooms")
    students_by_id = {s.matriculation_number: s for s in students}

    greedy_result = assign(students, venue, forced, algorithm="greedy")
    ga_result = assign(
        students,
        venue,
        forced,
        algorithm="genetic",
        ga_config=GAConfig(population_size=20, generations=20, seed=5),
    )

    for result in (greedy_result, ga_result):
        by_id = {s.matriculation_number: s for s in result.students}
        assert result.nta_rooms == ["NTA"]
        # Mit drei Endziffern teilen sich fünf Prüflinge den Code "471", es gibt
        # aber nur vier Räume. Erst vier Endziffern reichen.
        assert result.code_length == 4
        assert find_hard_violations(result.plan, venue, by_id) == []
        assert find_code_violations(result.plan, venue, by_id) == []
        assert find_nta_violations(result.plan, venue, by_id, result.nta_rooms) == []

    # Der GA nutzt die Kapazität besser aus als die Baseline-Heuristik.
    assert len(ga_result.plan.assignments) >= len(greedy_result.plan.assignments)
