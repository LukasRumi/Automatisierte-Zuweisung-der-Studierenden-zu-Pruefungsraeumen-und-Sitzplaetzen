"""Tests der Raumvorgaben (s, r) ∈ F_R.

Eine Raumvorgabe legt nur den Raum fest, den Platz waehlt das Verfahren. Die
reale Teilnehmerliste enthaelt keine einzige solche Vorgabe, die Faelle hier
sind daher konstruiert.
"""

import json

import pytest

from pruefung.algorithms.first_fit import first_fit_assign
from pruefung.algorithms.genetic import GAConfig, repair_hard_violations
from pruefung.algorithms.greedy import greedy_assign
from pruefung.cli import main
from pruefung.constraints import (
    compute_neighbors,
    find_all_violations,
    find_room_requirement_violations,
    seat_conflicts,
    seat_conflicts_with_code,
)
from pruefung.models import ForcedAssignment, SeatingPlan, Student, Venue
from pruefung.parsing.rooms import parse_room_grid
from pruefung.parsing.students import parse_students_csv
from pruefung.pipeline import assign
from pruefung.requirements import ineffective_notes, resolve_room_requirements
from pruefung.room_assignment import fill_with_exceptions

ALGORITHMS = ("greedy", "first-fit", "genetic")
SMALL_GA = GAConfig(population_size=20, generations=20, seed=3)


def _venue(grids: dict[str, list[str]]) -> Venue:
    rooms, seats = {}, {}
    for name, grid in grids.items():
        room, room_seats = parse_room_grid(name, grid)
        rooms[name] = room
        seats.update(room_seats)
    return Venue(rooms=rooms, seats=seats, neighbors=compute_neighbors(seats))


def _student(index: int, group: str, last_name: str, **extra) -> Student:
    number = f"{100 + index}1"
    return Student(
        matriculation_number=number,
        seminar_group=group,
        name=f"{last_name}, Vorname",
        **extra,
    )


def _two_rooms() -> Venue:
    # Je Raum vier Plaetze in einer Reihe, R1 kommt in Lesereihenfolge zuerst.
    return _venue({"R1": ["X.X.X.X"], "R2": ["X.X.X.X"]})


def _eight(required: dict[int, str]) -> list[Student]:
    """Acht Prueflinge mit eigener Gruppe, sodass nur die Vorgabe bindet."""
    return [
        _student(i, f"G{i}", f"{chr(65 + i)}name", accommodation=required.get(i, ""))
        for i in range(8)
    ]


def _room_of(result, number: str) -> str:
    seat = result.plan.seat_of(number)
    assert seat is not None, f"{number} ist unversorgt"
    return seat.split(":")[0]


# --- Einlesen und Aufloesung ------------------------------------------------


def test_a_bare_room_name_is_kept_as_note_by_the_parser(tmp_path):
    # Beim Einlesen sind die Raeume noch unbekannt. Ein blosser Raumname
    # darf daher weder verworfen noch als fester Platz gelesen werden.
    liste = tmp_path / "liste.csv"
    liste.write_text("7300811;25INB-1;Albrecht, Anna;FE006\n", encoding="utf-8")

    students, forced = parse_students_csv(liste)

    assert students[0].accommodation == "FE006"
    assert forced == []


def test_a_note_naming_a_room_becomes_a_room_requirement():
    venue = _two_rooms()
    people = [_student(0, "G1", "Aname", accommodation="r2")]

    resolved = resolve_room_requirements(people, venue, [], [])

    # Gross- und Kleinschreibung spielt keine Rolle, gespeichert wird der
    # Raumname in der Schreibweise der Raumdatei.
    assert resolved[0].required_room == "R2"


def test_other_notes_stay_notes_and_are_reported():
    venue = _two_rooms()
    people = [
        _student(0, "G1", "Aname", accommodation="R3"),
        _student(1, "G1", "Bname", accommodation="Verlaengerte Bearbeitungszeit"),
        _student(2, "G1", "Cname", accommodation="R1"),
        _student(3, "G1", "Dname", accommodation="NTA"),
    ]

    resolved = resolve_room_requirements(people, venue, [], [])

    assert [s.required_room for s in resolved] == ["", "", "R1", ""]
    # Ein vertippter Raumname wie "R3" soll im Bericht auffallen.
    assert ineffective_notes(resolved, []) == {
        "1001": "R3",
        "1011": "Verlaengerte Bearbeitungszeit",
    }


def test_a_requirement_for_the_nta_room_is_rejected():
    # Der Wertebereich waere leer: Die Raumbindung der Nachteilsausgleiche
    # verschliesst den NTA-Raum allen anderen Prueflingen.
    venue = _venue({"R1": ["X.X.X.X"], "R1_nta": ["X.X.X.X"]})
    people = [_student(0, "G1", "Aname", accommodation="R1_nta")]

    with pytest.raises(ValueError, match="NTA-Raum"):
        resolve_room_requirements(people, venue, ["R1_nta"], [])


def test_an_nta_student_cannot_be_bound_to_a_regular_room():
    venue = _venue({"R1": ["X.X.X.X"], "NTA": ["X.X.X.X"]})
    people = [_student(0, "G1", "Aname", accommodation="NTA", required_room="R1")]

    with pytest.raises(ValueError, match="Nachteilsausgleich"):
        resolve_room_requirements(people, venue, ["NTA"], [])


def test_an_unknown_required_room_is_rejected():
    people = [_student(0, "G1", "Aname", required_room="R9")]

    with pytest.raises(ValueError, match="unbekannten Raum"):
        resolve_room_requirements(people, _two_rooms(), [], [])


def test_a_fixed_seat_in_another_room_is_rejected():
    people = [_student(0, "G1", "Aname", required_room="R2")]
    forced = [ForcedAssignment(matriculation_number="1001", room="R1", seat_label="A1")]

    with pytest.raises(ValueError, match="fester Platz"):
        resolve_room_requirements(people, _two_rooms(), [], forced)


def test_more_requirements_than_seats_are_rejected():
    people = [_student(i, f"G{i}", "Name", required_room="R1") for i in range(5)]

    with pytest.raises(ValueError, match="nur 4"):
        resolve_room_requirements(people, _two_rooms(), [], [])


# --- Restriktion und Validierung ---------------------------------------------


def test_seat_conflicts_rejects_a_seat_outside_the_required_room():
    venue = _two_rooms()
    student = _student(0, "G1", "Aname", required_room="R2")
    plan = SeatingPlan()

    assert seat_conflicts(venue.assignable_in("R1")[0], student, plan, {}, venue)
    assert not seat_conflicts(venue.assignable_in("R2")[0], student, plan, {}, venue)


def test_a_violated_requirement_is_found_and_counted_once():
    venue = _two_rooms()
    student = _student(0, "G1", "Aname", required_room="R2")
    seat = venue.assignable_in("R1")[0]
    plan = SeatingPlan({seat: student.matriculation_number})
    by_id = {student.matriculation_number: student}

    assert find_room_requirement_violations(plan, venue, by_id) == [seat]
    assert find_all_violations(plan, venue, by_id) == [(seat, seat)]


def test_the_code_check_ignores_the_seat_itself():
    # Die Reparatur des GA prueft einen Tausch, nachdem sie ihn ausgefuehrt
    # hat. Vorher fand sie dabei den Code des eingetauschten Prueflings
    # selbst und verwarf jeden Tausch.
    venue = _two_rooms()
    student = _student(0, "G1", "Aname", display_code="00")
    seat = venue.assignable_in("R1")[0]
    plan = SeatingPlan({seat: student.matriculation_number})
    by_id = {student.matriculation_number: student}

    assert not seat_conflicts_with_code(seat, "00", plan, by_id, venue)


# --- Verfahren ---------------------------------------------------------------


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_every_algorithm_seats_a_late_student_in_the_first_room(algorithm):
    # Der Pruefling steht in der Sortierung ganz hinten. Ohne Vorrang waere
    # R1 laengst voll, bevor er an der Reihe ist.
    people = _eight({7: "R1"})

    result = assign(people, _two_rooms(), algorithm=algorithm, ga_config=SMALL_GA)

    assert _room_of(result, "1071") == "R1"
    assert result.plan.unassigned == []


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_every_algorithm_seats_an_early_student_in_the_second_room(algorithm):
    # Der Pruefling steht vorn, sein Raum kommt aber erst an zweiter Stelle.
    # Die Plaetze von R1 duerfen dabei nicht verloren gehen.
    people = _eight({0: "R2"})

    result = assign(people, _two_rooms(), algorithm=algorithm, ga_config=SMALL_GA)

    assert _room_of(result, "1001") == "R2"
    assert result.plan.unassigned == []


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_several_requirements_are_all_met(algorithm):
    people = _eight({0: "R2", 3: "R2", 5: "R1", 6: "R1"})

    result = assign(people, _two_rooms(), algorithm=algorithm, ga_config=SMALL_GA)

    rooms = {number: _room_of(result, number) for number in ("1001", "1031", "1051", "1061")}
    assert rooms == {"1001": "R2", "1031": "R2", "1051": "R1", "1061": "R1"}
    by_id = {s.matriculation_number: s for s in result.students}
    assert find_all_violations(result.plan, _two_rooms(), by_id) == []


def test_greedy_and_first_fit_keep_the_order_without_requirements():
    # Ohne Vorgaben darf sich an den Ergebnissen nichts aendern.
    venue = _two_rooms()
    people = _eight({})

    assert greedy_assign(people, venue).assignments == {
        seat: f"{100 + i}1" for i, seat in enumerate(venue.seats_in_reading_order())
    }
    assert first_fit_assign(people, venue).assignments == greedy_assign(people, venue).assignments


def test_a_purely_random_ga_population_still_meets_the_requirement():
    # Ohne konstruktive Startindividuen haengt die Einhaltung an Fitness,
    # Reparatur und Raeumung. Das Ergebnis muss trotzdem zulaessig sein.
    people = _eight({7: "R1", 0: "R2"})
    config = GAConfig(population_size=10, generations=2, seed=1, constructive_share=0.0)

    result = assign(people, _two_rooms(), algorithm="genetic", ga_config=config)

    by_id = {s.matriculation_number: s for s in result.students}
    assert find_all_violations(result.plan, _two_rooms(), by_id) == []


def test_repair_swaps_a_student_into_the_required_room():
    # Beide Raeume sind voll, der Pruefling sitzt im falschen. Nur ein Tausch
    # hilft, und er muss gelingen, obwohl alle Anzeigecodes gesetzt sind.
    venue = _two_rooms()
    people = [
        _student(i, f"G{i}", f"{chr(65 + i)}name", display_code=f"{i:02d}")
        for i in range(8)
    ]
    people[0] = _student(0, "G0", "Aname", display_code="00", required_room="R2")
    seats = venue.seats_in_reading_order()
    plan = SeatingPlan({seat: s.matriculation_number for seat, s in zip(seats, people)})
    by_id = {s.matriculation_number: s for s in people}

    repaired = repair_hard_violations(plan, venue, by_id)

    assert find_all_violations(repaired, venue, by_id) == []
    assert venue.seats[repaired.seat_of("1001")].room == "R2"
    assert len(repaired.assignments) == 8


# --- Einteilungsbasierte Raumzuordnung ----------------------------------------


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_the_requirement_wins_over_the_assignment_rule(algorithm):
    venue = _venue({"R1": ["X.X.X.X", "X.X.X.X"], "R2": ["X.X.X.X", "X.X.X.X"]})
    people = [
        _student(i, f"G{i % 2 + 1}", f"{chr(65 + i)}name") for i in range(8)
    ] + [_student(9, "G1", "Zname", required_room="R1")]

    result = assign(
        people, venue, algorithm=algorithm, room_assignment="rules", ga_config=SMALL_GA
    )

    assert _room_of(result, "1091") == "R1"


def test_filling_with_exceptions_respects_the_requirement():
    # R1 ist voll. Der gebundene Pruefling darf nicht als Ausnahme nach R2
    # ausweichen, der ungebundene schon.
    venue = _two_rooms()
    seated = [_student(i, f"G{i}", f"{chr(65 + i)}name") for i in range(4)]
    bound = _student(4, "G4", "Ename", required_room="R1")
    free = _student(5, "G5", "Fname")
    plan = SeatingPlan(
        {seat: s.matriculation_number for seat, s in zip(venue.assignable_in("R1"), seated)},
        [bound.matriculation_number, free.matriculation_number],
    )

    filled, _ = fill_with_exceptions(plan, venue, seated + [bound, free])

    assert filled.unassigned == [bound.matriculation_number]
    assert venue.seats[filled.seat_of(free.matriculation_number)].room == "R2"


# --- Kommandozeile und Bericht -------------------------------------------------


def test_the_cli_reads_a_room_requirement_and_reports_it(tmp_path, capsys):
    liste = tmp_path / "liste.csv"
    liste.write_text(
        "1000011;G1;Albrecht, Anna;\n"
        "1000021;G2;Berger, Ben;R2\n"
        "1000031;G3;Conrad, Cem;R7\n",
        encoding="utf-8",
    )
    raeume = tmp_path / "raeume"
    raeume.mkdir()
    (raeume / "R1.txt").write_text("X.X.X.X\n", encoding="utf-8")
    (raeume / "R2.txt").write_text("X.X.X.X\n", encoding="utf-8")
    out = tmp_path / "out"

    code = main([
        "assign",
        "--students", str(liste),
        "--rooms", str(raeume),
        "--output", str(out),
        "--algorithm", "greedy",
        "--format", "text",
        "--reserve-seats", "0",
    ])

    assert code == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["raumvorgaben"] == {"1000021": "R2"}
    assert report["raumvorgaben_verletzungen"] == 0
    assert report["vermerke_ohne_wirkung"] == {"1000031": "R7"}
    stdout = capsys.readouterr().out
    assert "Raumvorgaben: 1" in stdout
    assert "1000031: R7" in stdout
