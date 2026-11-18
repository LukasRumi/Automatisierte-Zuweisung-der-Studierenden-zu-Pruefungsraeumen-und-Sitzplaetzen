from pruefung.constraints import compute_neighbors
from pruefung.models import SeatingPlan, Student, Venue
from pruefung.output.assignment_sheet import (
    render_assignment_sheet,
    write_assignment_sheet,
)
from pruefung.parsing.rooms import parse_room_grid


def _venue():
    room_a, seats_a = parse_room_grid("FE006", ["XXX"])
    room_b, seats_b = parse_room_grid("TR129", ["XXX"])
    seats = {**seats_a, **seats_b}
    return Venue(
        rooms={"FE006": room_a, "TR129": room_b},
        seats=seats,
        neighbors=compute_neighbors(seats),
    )


def _student(number: str, code: str, name: str) -> Student:
    return Student(
        matriculation_number=number,
        seminar_group="25INB-1",
        name=name,
        display_code=code,
    )


def _students():
    return {
        "111": _student("111", "11", "Albrecht, Anna"),
        "222": _student("222", "22", "Zimmer, Zoe"),
        "333": _student("333", "33", "Brandt, Ben"),
    }


RULES = {"TR129": "A-F", "FE006": "P-Z"}


def _hat_abschnitt(text: str, titel: str) -> bool:
    """Prueft auf eine Abschnittsueberschrift, nicht auf das blosse Wort."""
    return titel in [z.strip() for z in text.splitlines()]


def test_sheet_lists_the_rules_sorted_by_letter_range():
    # Gesucht wird der eigene Anfangsbuchstabe, nicht der Raumname.
    plan = SeatingPlan(assignments={"TR129:A1": "111", "FE006:A1": "222"})
    text = render_assignment_sheet(_venue(), plan, _students(), RULES)

    zeilen = [z for z in text.splitlines() if z.strip()]
    a_bereich = next(i for i, z in enumerate(zeilen) if z.startswith("A-F"))
    p_bereich = next(i for i, z in enumerate(zeilen) if z.startswith("P-Z"))
    assert a_bereich < p_bereich


def test_sheet_names_the_room_of_a_deviating_code():
    # Brandt faellt unter A-F, sitzt aber in FE006. Wer das hier liest, geht
    # gleich dorthin, statt erst TR129 aufzusuchen.
    plan = SeatingPlan(
        assignments={"TR129:A1": "111", "FE006:A1": "222", "FE006:A3": "333"}
    )
    text = render_assignment_sheet(
        _venue(), plan, _students(), RULES, {"TR129": {"333": "FE006"}}
    )

    assert _hat_abschnitt(text, "Codes mit eigener Angabe")
    assert "33" in text
    assert "FE006" in text
    assert "Brandt" not in text


def test_sheet_without_deviations_has_no_lookup_list():
    plan = SeatingPlan(assignments={"TR129:A1": "111", "FE006:A1": "222"})
    text = render_assignment_sheet(_venue(), plan, _students(), RULES, {})

    assert not _hat_abschnitt(text, "Codes mit eigener Angabe")
    # Dann darf der Hinweis oben auch nicht darauf verweisen.
    assert "Liste unten" not in text


def test_all_special_codes_share_one_sorted_list():
    # Der Kern des Zettels: Wer seinen Code in einer ersten Liste nicht
    # findet, folgt dem Buchstaben und liest eine zweite nie. Also gibt es
    # nur eine, und sie enthaelt beide Arten von Sonderfall.
    students = _students()
    students["444"] = _student("444", "11", "Arnold, Arne")
    plan = SeatingPlan(
        assignments={
            "TR129:A1": "111",
            "FE006:A1": "222",
            "FE006:A2": "333",
            "FE006:A3": "444",
        }
    )
    text = render_assignment_sheet(
        _venue(), plan, students, RULES, {"TR129": {"333": "FE006", "444": "FE006"}}
    )

    eintraege = [
        z.split()[0]
        for z in text.splitlines()
        if z and not z.startswith(" ") and z.split()[0].isdigit()
    ]
    assert eintraege == sorted(eintraege)
    assert "11" in eintraege and "33" in eintraege


def test_sheet_splits_an_ambiguous_code_by_the_next_letter():
    # Zwei Pruefline mit Code 11: einer sitzt in TR129, der andere faellt
    # ebenfalls unter A-F, sitzt aber in FE006. Albrecht und Arnold trennt
    # erst der zweite Buchstabe.
    students = _students()
    students["444"] = _student("444", "11", "Arnold, Arne")
    plan = SeatingPlan(
        assignments={"TR129:A1": "111", "FE006:A1": "222", "FE006:A3": "444"}
    )
    text = render_assignment_sheet(
        _venue(), plan, students, RULES, {"TR129": {"444": "FE006"}}
    )

    assert _hat_abschnitt(text, "Codes mit eigener Angabe")
    assert "Nachname mit AL" in text
    assert "Nachname mit AR" in text
    assert "Aufsicht" not in text


def test_sheet_falls_back_to_the_invigilator_for_identical_surnames():
    students = _students()
    students["444"] = _student("444", "11", "Albrecht, Bert")
    plan = SeatingPlan(
        assignments={"TR129:A1": "111", "FE006:A1": "222", "FE006:A3": "444"}
    )
    text = render_assignment_sheet(
        _venue(), plan, students, RULES, {"TR129": {"444": "FE006"}}
    )

    assert _hat_abschnitt(text, "Codes mit eigener Angabe")
    assert "Aufsicht" in text
    assert "TR129 oder FE006" in text


def test_sheet_without_rules_points_to_the_doors():
    plan = SeatingPlan(assignments={"TR129:A1": "111"})
    text = render_assignment_sheet(_venue(), plan, _students(), None)

    assert "keine Einteilung" in text
    assert "Türen" in text


def test_write_assignment_sheet_creates_both_formats(tmp_path):
    plan = SeatingPlan(assignments={"TR129:A1": "111", "FE006:A1": "222"})
    pfade = write_assignment_sheet(
        _venue(), plan, _students(), tmp_path, ("text", "pdf"), RULES
    )

    namen = {p.name for p in pfade}
    assert namen == {"raumzuordnung.txt", "raumzuordnung.pdf"}
    assert (tmp_path / "raumzuordnung.txt").read_text(encoding="utf-8").startswith(
        "Raumzuordnung zur Prüfung"
    )


def test_sheet_never_shows_names_or_full_numbers():
    plan = SeatingPlan(
        assignments={"TR129:A1": "111", "FE006:A1": "222", "FE006:A3": "333"}
    )
    text = render_assignment_sheet(
        _venue(), plan, _students(), RULES, {"TR129": {"333": "FE006"}}
    )

    for student in _students().values():
        assert student.name not in text
        assert student.matriculation_number not in text
