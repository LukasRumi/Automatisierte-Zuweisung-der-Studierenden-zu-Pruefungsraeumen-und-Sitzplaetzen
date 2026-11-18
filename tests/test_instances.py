import pytest

from pruefung.instances import NAME_INITIAL_WEIGHTS, InstanceSpec, generate_instance
from pruefung.nta import split_by_nta_flag
from pruefung.parsing.rooms import SEAT_CHAR


def test_generated_instance_matches_the_requested_size():
    student_list, venue, nta_rooms = generate_instance(InstanceSpec(students=100, seed=1))
    assert len(student_list) == 100
    assert len({s.matriculation_number for s in student_list}) == 100
    assert nta_rooms == ["NTA"]


def test_utilisation_controls_the_available_capacity():
    tight = generate_instance(InstanceSpec(students=100, utilisation=0.95, seed=1))
    loose = generate_instance(InstanceSpec(students=100, utilisation=0.6, seed=1))

    def regular_seats(result):
        _, venue, nta = result
        return sum(
            len(current_room.seat_ids) for name, current_room in venue.rooms.items() if name not in nta
        )

    assert regular_seats(tight) < regular_seats(loose)


def test_generation_is_reproducible_for_a_fixed_seed():
    a = generate_instance(InstanceSpec(seed=7))
    b = generate_instance(InstanceSpec(seed=7))
    assert [s.matriculation_number for s in a[0]] == [s.matriculation_number for s in b[0]]
    assert [s.name for s in a[0]] == [s.name for s in b[0]]


def test_different_seeds_produce_different_instances():
    a = generate_instance(InstanceSpec(seed=1))
    b = generate_instance(InstanceSpec(seed=2))
    assert [s.matriculation_number for s in a[0]] != [s.matriculation_number for s in b[0]]


def test_rooms_follow_the_realistic_seating_pattern():
    _, venue, _ = generate_instance(InstanceSpec(seed=3))
    for current_room in venue.rooms.values():
        for line in current_room.grid:
            # Kein Raster enthält zwei unmittelbar benachbarte nutzbare Plätze.
            assert SEAT_CHAR * 2 not in line


def test_names_are_present_and_follow_the_weighted_distribution():
    student_list, _, _ = generate_instance(InstanceSpec(students=400, seed=5))
    assert all("," in s.name for s in student_list)
    initials = [s.last_name[0] for s in student_list]
    assert set(initials) <= set(NAME_INITIAL_WEIGHTS)
    # S ist der mit Abstand häufigste Anfangsbuchstabe und sollte dominieren.
    assert initials.count("S") > initials.count("Q")


def test_nta_fraction_is_respected():
    student_list, _, _ = generate_instance(
        InstanceSpec(students=200, nta_fraction=0.05, seed=2)
    )
    nta, _ = split_by_nta_flag(student_list)
    assert len(nta) == 10


def test_invalid_specification_is_rejected():
    with pytest.raises(ValueError, match="Auslastungsgrad"):
        generate_instance(InstanceSpec(utilisation=0))
    with pytest.raises(ValueError, match="positiv"):
        generate_instance(InstanceSpec(rooms=0))
