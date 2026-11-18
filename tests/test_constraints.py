from pruefung.constraints import (
    DEFAULT_NEIGHBOR_RADIUS,
    SORT_SCALE,
    compactness_gap_cost,
    compute_neighbors,
    find_code_violations,
    find_hard_violations,
    fragmentation_cost,
    seat_conflicts,
    seat_conflicts_with_group,
    sort_key,
    sorting_cost,
)
from pruefung.models import SeatingPlan, Student, Venue
from pruefung.parsing.rooms import parse_room_grid


def _make_venue(grid, radius=1.45):
    """Testräume werden mit explizitem Radius gebaut, damit die Aussagen über die
    Geometrie unabhängig vom eingestellten Standardwert gelten."""
    room, seats = parse_room_grid("R", grid)
    neighbors = compute_neighbors(seats, radius=radius)
    return Venue(rooms={"R": room}, seats=seats, neighbors=neighbors)


def test_adjacent_seats_in_a_row_are_neighbors():
    venue = _make_venue(["XXX"], radius=1.45)
    assert "R:A2" in venue.neighbors["R:A1"]
    assert "R:A3" not in venue.neighbors["R:A1"]  # zwei Plätze entfernt, kein Nachbar


def test_seats_across_an_aisle_are_not_neighbors():
    venue = _make_venue(["XX_XX"], radius=1.45)
    assert "R:A3" not in venue.neighbors["R:A2"]


def test_seats_in_adjacent_rows_are_neighbors():
    venue = _make_venue(["XX", "XX"], radius=1.45)
    assert "R:B1" in venue.neighbors["R:A1"]  # orthogonal
    assert "R:B2" in venue.neighbors["R:A1"]  # diagonal


def test_default_radius_covers_the_vicinity_of_a_real_seating_pattern():
    # Reale Bestuhlung: jeder zweite Sitz bleibt frei ("X.X.X.X").
    venue = _make_venue(["X.X.X", "X.X.X"], radius=DEFAULT_NEIGHBOR_RADIUS)
    assert "R:B1" in venue.neighbors["R:A1"]  # direkt dahinter (Abstand 1.0)
    assert "R:A2" in venue.neighbors["R:A1"]  # seitlich (Abstand 2.0)
    assert "R:B2" in venue.neighbors["R:A1"]  # diagonal (Abstand 2.24)
    assert "R:A3" not in venue.neighbors["R:A1"]  # zwei Sitze weiter (Abstand 4.0)


def test_code_violation_detected_within_a_room_but_not_across_rooms():
    room_a, seats_a = parse_room_grid("A", ["XX"])
    room_b, seats_b = parse_room_grid("B", ["XX"])
    seats = {**seats_a, **seats_b}
    venue = Venue(rooms={"A": room_a, "B": room_b}, seats=seats, neighbors=compute_neighbors(seats))
    students_by_id = {
        "1": Student(matriculation_number="1", seminar_group="G1", display_code="008"),
        "2": Student(matriculation_number="2", seminar_group="G2", display_code="008"),
    }

    # Gleicher Code im selben Raum: auf dem Aushang nicht unterscheidbar.
    same_room = SeatingPlan(assignments={"A:A1": "1", "A:A2": "2"})
    assert find_code_violations(same_room, venue, students_by_id) == [("A:A1", "A:A2")]

    # Gleicher Code in verschiedenen Räumen: je Raum ein eigener Aushang, daher zulässig.
    separated = SeatingPlan(assignments={"A:A1": "1", "B:A1": "2"})
    assert find_code_violations(separated, venue, students_by_id) == []


def test_empty_code_is_exempt_from_the_uniqueness_rule():
    venue = _make_venue(["XX"])
    students_by_id = {
        "1": Student(matriculation_number="1", seminar_group="G1"),
        "2": Student(matriculation_number="2", seminar_group="G2"),
    }
    plan = SeatingPlan(assignments={"R:A1": "1", "R:A2": "2"})
    assert find_code_violations(plan, venue, students_by_id) == []


def test_seat_conflicts_combines_both_hard_restrictions():
    venue = _make_venue(["XX"])
    students_by_id = {"1": Student(matriculation_number="1", seminar_group="G1", display_code="008")}
    plan = SeatingPlan(assignments={"R:A1": "1"})

    same_group = Student(matriculation_number="2", seminar_group="G1", display_code="123")
    same_code = Student(matriculation_number="3", seminar_group="G2", display_code="008")
    harmless = Student(matriculation_number="4", seminar_group="G2", display_code="123")

    assert seat_conflicts("R:A2", same_group, plan, students_by_id, venue)
    assert seat_conflicts("R:A2", same_code, plan, students_by_id, venue)
    assert not seat_conflicts("R:A2", harmless, plan, students_by_id, venue)


def test_seat_conflicts_with_group_detects_same_group_neighbor():
    venue = _make_venue(["XX"])
    plan = SeatingPlan(assignments={"R:A1": "111"})
    students_by_id = {"111": Student(matriculation_number="111", seminar_group="G1")}
    assert seat_conflicts_with_group("R:A2", "G1", plan, students_by_id, venue.neighbors)
    assert not seat_conflicts_with_group("R:A2", "G2", plan, students_by_id, venue.neighbors)


def test_find_hard_violations_reports_conflicting_pairs():
    venue = _make_venue(["XX"])
    plan = SeatingPlan(assignments={"R:A1": "111", "R:A2": "222"})
    students_by_id = {
        "111": Student(matriculation_number="111", seminar_group="G1"),
        "222": Student(matriculation_number="222", seminar_group="G1"),
    }
    violations = find_hard_violations(plan, venue, students_by_id)
    assert violations == [("R:A1", "R:A2")]


def test_fragmentation_cost_counts_distinct_group_room_pairs():
    venue = _make_venue(["XX"])
    plan = SeatingPlan(assignments={"R:A1": "111", "R:A2": "222"})
    students_by_id = {
        "111": Student(matriculation_number="111", seminar_group="G1"),
        "222": Student(matriculation_number="222", seminar_group="G1"),
    }
    assert fragmentation_cost(plan, venue, students_by_id) == 1


def test_compactness_gap_cost_penalizes_holes_in_a_row():
    venue = _make_venue(["XXXX"])
    plan_block = SeatingPlan(assignments={"R:A1": "1", "R:A2": "2"})
    plan_gap = SeatingPlan(assignments={"R:A1": "1", "R:A4": "2"})
    assert compactness_gap_cost(plan_block, venue) == 0
    assert compactness_gap_cost(plan_gap, venue) == 2


def test_sorting_cost_follows_surnames_when_names_are_present():
    venue = _make_venue(["XXX"])
    students_by_id = {
        "1": Student(matriculation_number="1", seminar_group="G", name="Albrecht, A"),
        "2": Student(matriculation_number="2", seminar_group="G", name="Baumann, B"),
        "3": Student(matriculation_number="3", seminar_group="G", name="Zimmer, Z"),
    }
    alphabetical = SeatingPlan(assignments={"R:A1": "1", "R:A2": "2", "R:A3": "3"})
    shuffled = SeatingPlan(assignments={"R:A1": "3", "R:A2": "1", "R:A3": "2"})
    assert sorting_cost(alphabetical, venue, students_by_id) < sorting_cost(
        shuffled, venue, students_by_id
    )


def test_sort_key_falls_back_to_the_number_without_a_name():
    with_name = Student(matriculation_number="4500011", seminar_group="G", name="Albrecht, A")
    without_name = Student(matriculation_number="4500011", seminar_group="G")
    assert sort_key(with_name) != sort_key(without_name)
    # Beide Schlüsselarten liegen im selben Wertebereich, damit w2 vergleichbar bleibt.
    assert 0 <= sort_key(with_name) <= SORT_SCALE
    assert 0 <= sort_key(without_name) <= SORT_SCALE


def test_sorting_cost_rewards_ascending_neighboring_numbers():
    venue = _make_venue(["XXX"])
    students_by_id = {
        "1": Student(matriculation_number="1", seminar_group="G"),
        "2": Student(matriculation_number="2", seminar_group="G"),
        "9": Student(matriculation_number="9", seminar_group="G"),
    }
    sorted_plan = SeatingPlan(assignments={"R:A1": "1", "R:A2": "2", "R:A3": "9"})
    unsorted_plan = SeatingPlan(assignments={"R:A1": "9", "R:A2": "1", "R:A3": "2"})
    # Die Reihenfolge 1,2,9 hat geringere Sprungkosten als 9,1,2.
    assert sorting_cost(sorted_plan, venue, students_by_id) < sorting_cost(
        unsorted_plan, venue, students_by_id
    )
