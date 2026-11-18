import math

from pruefung.parsing.rooms import FULL_WIDTH, HALF_WIDTH, ROW_HEIGHT, parse_room_grid


def test_simple_grid_produces_expected_seat_count_and_labels():
    grid = ["XXX_XXX", "XXX_XXX"]
    room, seats = parse_room_grid("Test", grid)

    assert room.name == "Test"
    assert len(seats) == 12
    assert room.seat_ids[0] == "Test:A1"
    assert room.seat_ids[5] == "Test:A6"
    assert room.seat_ids[6] == "Test:B1"


def test_blocked_and_aisle_characters_are_not_seats():
    grid = ["XX.XX"]
    _, seats = parse_room_grid("Test", grid)
    assert len(seats) == 4


def test_half_width_character_shrinks_horizontal_spacing():
    # "X<X": zwei Sitzplätze, getrennt durch einen Platz halber Breite.
    _, seats = parse_room_grid("Test", ["X<X"])
    seat_a, seat_b = seats["Test:A1"], seats["Test:A2"]
    distance = seat_b.x - seat_a.x
    assert math.isclose(distance, FULL_WIDTH / 2 + HALF_WIDTH + FULL_WIDTH / 2)

    # Referenz: zwei Sitzplätze mit einem regulären Zwischenraum liegen weiter auseinander.
    _, wide_seats = parse_room_grid("Test", ["X_X"])
    wide_a, wide_b = wide_seats["Test:A1"], wide_seats["Test:A2"]
    assert (wide_b.x - wide_a.x) > distance


def test_row_height_scales_with_row_index():
    _, seats = parse_room_grid("Test", ["X", "X"])
    assert seats["Test:A1"].y == 0
    assert seats["Test:B1"].y == ROW_HEIGHT


def test_row_labels_beyond_z_use_double_letters():
    grid = ["X"] * 27
    _, seats = parse_room_grid("Test", grid)
    assert "Test:Z1" in seats
    assert "Test:AA1" in seats
