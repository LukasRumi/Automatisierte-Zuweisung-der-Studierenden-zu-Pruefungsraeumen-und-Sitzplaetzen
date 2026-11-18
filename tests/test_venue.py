from pathlib import Path

from pruefung.venue import load_venue

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
ROOMS = EXAMPLES / "pruefung1" / "rooms"


def test_load_venue_reads_all_rooms():
    venue = load_venue(ROOMS)
    assert set(venue.rooms) == {"FE006", "NTA", "TR129", "TRA140"}
    assert len(venue.seats) == 155
    assert venue.reserved == frozenset()


def test_reserved_seats_stay_part_of_the_room():
    # Die Reserve verschwindet nicht aus dem Modell: Der Aushangplan soll die
    # Bestuhlung vollständig abbilden.
    baseline = load_venue(ROOMS)
    enabled = load_venue(ROOMS, reserve_seats=2)

    assert len(enabled.seats) == len(baseline.seats)
    for name, current_room in enabled.rooms.items():
        assert current_room.seat_ids == baseline.rooms[name].seat_ids


def test_reserved_seats_are_not_assignable():
    enabled = load_venue(ROOMS, reserve_seats=2)

    assert len(enabled.reserved) == 2 * len(enabled.rooms)
    assignable = set(enabled.seats_in_reading_order())
    assert assignable.isdisjoint(enabled.reserved)
    assert len(assignable) == len(enabled.seats) - len(enabled.reserved)


def test_reserve_takes_the_rearmost_seats_of_each_room():
    enabled = load_venue(ROOMS, reserve_seats=2)
    for name, current_room in enabled.rooms.items():
        assert set(current_room.seat_ids[-2:]) <= enabled.reserved
        assert enabled.assignable_in(name) == current_room.seat_ids[:-2]


def test_reserve_of_zero_changes_nothing():
    assert load_venue(ROOMS, reserve_seats=0).reserved == frozenset()
