import pytest

from pruefung.constraints import compute_neighbors
from pruefung.models import SeatingPlan, Student, Venue
from pruefung.nta import (
    find_nta_rooms,
    find_nta_violations,
    is_nta,
    split_by_nta_flag,
    subvenue,
)
from pruefung.parsing.rooms import parse_room_grid


def _venue(grids: dict[str, list[str]]) -> Venue:
    rooms = {}
    seats = {}
    for name, grid in grids.items():
        room, room_seats = parse_room_grid(name, grid)
        rooms[name] = room
        seats.update(room_seats)
    return Venue(rooms=rooms, seats=seats, neighbors=compute_neighbors(seats))


def _student(matriculation_number: str, group: str = "G1", accommodation: str = "") -> Student:
    return Student(
        matriculation_number=matriculation_number,
        seminar_group=group,
        accommodation=accommodation,
    )


def test_is_nta_is_case_insensitive():
    assert is_nta(_student("1", accommodation="NTA"))
    assert is_nta(_student("2", accommodation=" nta "))
    assert not is_nta(_student("3", accommodation="Verlaengerte Bearbeitungszeit"))
    assert not is_nta(_student("4"))


def test_split_by_nta_flag_preserves_all_students():
    students = [_student("1", accommodation="NTA"), _student("2"), _student("3")]
    nta, regular = split_by_nta_flag(students)
    assert [s.matriculation_number for s in nta] == ["1"]
    assert [s.matriculation_number for s in regular] == ["2", "3"]


def test_find_nta_rooms_uses_naming_convention():
    venue = _venue({"HS5": ["XX"], "NTA": ["XX"]})
    assert find_nta_rooms(venue) == ["NTA"]

    venue = _venue({"HS5": ["XX"], "raum4_nta": ["XX"]})
    assert find_nta_rooms(venue) == ["raum4_nta"]

    venue = _venue({"HS5": ["XX"], "SR1": ["XX"]})
    assert find_nta_rooms(venue) == []


def test_find_nta_rooms_override_must_exist():
    venue = _venue({"HS5": ["XX"], "NTA": ["XX"]})
    assert find_nta_rooms(venue, override="HS5") == ["HS5"]
    with pytest.raises(ValueError):
        find_nta_rooms(venue, override="Gibtsnicht")


def test_subvenue_includes_and_excludes_rooms():
    venue = _venue({"HS5": ["XX"], "NTA": ["XX"]})

    only_nta = subvenue(venue, {"NTA"}, include=True)
    assert set(only_nta.rooms) == {"NTA"}
    assert all(seat.room == "NTA" for seat in only_nta.seats.values())

    without_nta = subvenue(venue, {"NTA"}, include=False)
    assert set(without_nta.rooms) == {"HS5"}
    assert all(seat.room == "HS5" for seat in without_nta.seats.values())
    # Nachbarschaften bleiben innerhalb der verbleibenden Plätze konsistent.
    assert all(
        neighbor in without_nta.seats
        for neighbors in without_nta.neighbors.values()
        for neighbor in neighbors
    )


def test_find_nta_violations_detects_both_directions():
    venue = _venue({"HS5": ["XX"], "NTA": ["XX"]})
    students_by_id = {
        "1": _student("1", accommodation="NTA"),
        "2": _student("2", group="G2"),
    }

    correct = SeatingPlan(assignments={"NTA:A1": "1", "HS5:A1": "2"})
    assert find_nta_violations(correct, venue, students_by_id, ["NTA"]) == []

    # NTA-Studierender außerhalb des NTA-Raums und regulärer Studierender darin.
    wrong = SeatingPlan(assignments={"HS5:A1": "1", "NTA:A1": "2"})
    assert find_nta_violations(wrong, venue, students_by_id, ["NTA"]) == ["HS5:A1", "NTA:A1"]
