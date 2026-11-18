from pruefung.constraints import compute_neighbors
from pruefung.models import SeatingPlan, Student, Venue
from pruefung.output.overview import (
    UNASSIGNED_MARKER,
    render_overview,
    render_room_overview,
    write_overview,
)
from pruefung.output.seatmap import BOARD
from pruefung.parsing.rooms import parse_room_grid


def _venue():
    room_a, seats_a = parse_room_grid("HS5", ["XX"])
    room_b, seats_b = parse_room_grid("SR1", ["XX"])
    seats = {**seats_a, **seats_b}
    return Venue(rooms={"HS5": room_a, "SR1": room_b}, seats=seats, neighbors=compute_neighbors(seats))


def _students():
    return [
        Student(matriculation_number="111", seminar_group="G1", name="Zimmer, Yusuf"),
        Student(matriculation_number="222", seminar_group="G2", name="Albrecht, Anna"),
        Student(matriculation_number="333", seminar_group="G3", name="Mayer, Marie"),
    ]


def test_overview_lists_name_room_and_seat():
    venue = _venue()
    students = _students()
    plan = SeatingPlan(assignments={"HS5:A1": "111", "SR1:A2": "222"})

    text = render_overview(venue, plan, students)

    assert "Zimmer, Yusuf" in text
    assert "HS5" in text and "A1" in text
    assert "SR1" in text and "A2" in text
    # Die volle Matrikelnummer gehört auf den internen Plan.
    assert "111" in text


def test_overview_is_sorted_alphabetically_by_name():
    venue = _venue()
    students = _students()
    plan = SeatingPlan(assignments={"HS5:A1": "111", "SR1:A1": "222", "SR1:A2": "333"})

    text_rows = render_overview(venue, plan, students).splitlines()
    positions = [
        next(i for i, z in enumerate(text_rows) if z.startswith(name))
        for name in ("Albrecht", "Mayer", "Zimmer")
    ]
    assert positions == sorted(positions)


def test_overview_marks_students_without_a_seat():
    venue = _venue()
    students = _students()
    plan = SeatingPlan(assignments={"HS5:A1": "111"}, unassigned=["222", "333"])

    text = render_overview(venue, plan, students)

    assert text.count(UNASSIGNED_MARKER) == 2
    assert "Ohne Platz: 2" in text


def test_write_overview_creates_a_plan_per_room_and_the_full_list(tmp_path):
    venue = _venue()
    plan = SeatingPlan(assignments={"HS5:A1": "111"})
    paths = write_overview(venue, plan, _students(), tmp_path)

    assert {p.name for p in paths} == {
        "aufsicht_HS5.txt",
        "aufsicht_HS5.pdf",
        "aufsicht_SR1.txt",
        "aufsicht_SR1.pdf",
        "uebersichtsplan.txt",
        "uebersichtsplan.pdf",
        "sitzplatzzuordnung.pdf",
    }
    assert all(p.exists() for p in paths)
    total = (tmp_path / "uebersichtsplan.txt").read_text(encoding="utf-8")
    assert "Übersichtsplan" in total
    assert all(
        p.read_bytes().startswith(b"%PDF") for p in paths if p.suffix == ".pdf"
    )


def test_write_overview_can_be_limited_to_one_format(tmp_path):
    venue = _venue()
    plan = SeatingPlan(assignments={"HS5:A1": "111"})
    paths = write_overview(venue, plan, _students(), tmp_path, formats=("pdf",))
    assert {p.suffix for p in paths} == {".pdf"}
    assert not (tmp_path / "uebersichtsplan.txt").exists()
    assert not (tmp_path / "aufsicht_HS5.txt").exists()


def test_internal_documents_also_land_in_one_file(tmp_path):
    # Die Aufsicht trifft oft erst kurz vor der Pruefung ein und soll ein
    # Dokument bekommen, nicht mehrere Dateien.
    venue = _venue()
    plan = SeatingPlan(assignments={"HS5:A1": "111"})
    write_overview(venue, plan, _students(), tmp_path, formats=("pdf",))

    gesamt = tmp_path / "sitzplatzzuordnung.pdf"
    roh = gesamt.read_bytes()
    einzeln = sum(
        (tmp_path / name).read_bytes().count(b"/Type /Page ")
        for name in ("aufsicht_HS5.pdf", "aufsicht_SR1.pdf", "uebersichtsplan.pdf")
    )
    assert roh.count(b"/Type /Page ") == einzeln
    # Die Raeume zuerst, die Gesamtliste dahinter.
    raum = roh.find(b"Aufsichtsplan Raum HS5")
    liste = roh.find("Übersichtsplan der".encode("cp1252"))
    assert 0 <= raum < liste


def test_room_overview_names_the_occupants_and_marks_the_board():
    venue = _venue()
    plan = SeatingPlan(assignments={"HS5:A1": "111", "HS5:A2": "222"})
    text = render_room_overview("HS5", venue, plan, _students())

    assert BOARD in text
    # Der interne Plan darf und soll Namen und volle Matrikelnummer nennen.
    assert "Zimmer, Yusuf" in text
    assert "111" in text
    # Wer nicht in diesem Raum sitzt, erscheint hier nicht.
    assert "Mayer, Marie" not in text
    assert "Belegt: 2 von 2" in text
