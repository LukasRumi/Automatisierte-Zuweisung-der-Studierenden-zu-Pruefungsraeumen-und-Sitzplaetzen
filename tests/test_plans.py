from pruefung.constraints import compute_neighbors
from pruefung.models import SeatingPlan, Student, Venue
from pruefung.output.plans import (
    EMPTY_MARKER,
    RESERVED_MARKER,
    render_room_plan,
    write_plans,
)
from pruefung.output.seatmap import BOARD
from pruefung.parsing.rooms import parse_room_grid


def _venue(reserved: frozenset[str] = frozenset()):
    room_a, seats_a = parse_room_grid("FE006", ["XXX"])
    room_b, seats_b = parse_room_grid("GU101", ["XX"])
    seats = {**seats_a, **seats_b}
    return Venue(
        rooms={"FE006": room_a, "GU101": room_b},
        seats=seats,
        neighbors=compute_neighbors(seats),
        reserved=reserved,
    )


def _students():
    return {
        "111": Student(
            matriculation_number="111",
            seminar_group="25INB-1",
            name="Albrecht, Anna",
            display_code="11",
        ),
        "222": Student(
            matriculation_number="222",
            seminar_group="25MIB-1",
            name="Berger, Ben",
            display_code="22",
        ),
    }


def _map_lines(text: str) -> list[str]:
    """Die Zeilen der Karte, also alles zwischen Tafelbalken und Legende."""
    text_rows = text.splitlines()
    start = next(i for i, z in enumerate(text_rows) if BOARD in z) + 1
    end = next(i for i, z in enumerate(text_rows) if z.startswith("Gezeigt sind"))
    return [z for z in text_rows[start:end] if z.strip()]


def test_room_plan_shows_the_display_code_and_not_the_name():
    plan = SeatingPlan(assignments={"FE006:A1": "111"})
    text = render_room_plan("FE006", _venue(), plan, _students())

    assert "11" in text
    assert "Albrecht" not in text
    # Die vollstaendige Matrikelnummer darf nicht auf dem Aushang stehen.
    assert "111" not in " ".join(_map_lines(text))


def test_exceptions_are_listed_under_the_rule():
    # Eine Einteilung ohne ihre Abweichungen ist fuer die Betroffenen
    # irrefuehrend: Sie stuenden im Raum, ohne von der Einteilung erfasst zu
    # sein, und fuehlten sich am falschen Ort.
    plan = SeatingPlan(assignments={"FE006:A1": "111", "FE006:A2": "222"})
    text = render_room_plan(
        "FE006", _venue(), plan, _students(), "25INB: A-K", ["222"]
    )

    assert "Zusätzlich in diesem Raum" in text
    assert "22" in text
    # Auch hier kein Klarname und keine volle Matrikelnummer.
    assert "Berger" not in text


def test_no_exception_line_without_exceptions():
    plan = SeatingPlan(assignments={"FE006:A1": "111"})
    text = render_room_plan("FE006", _venue(), plan, _students(), "25INB: A-K", [])

    assert "Zusätzlich" not in text


def test_exceptions_without_a_rule_stay_hidden():
    # Ohne Einteilung gibt es nichts, wovon abgewichen werden koennte.
    plan = SeatingPlan(assignments={"FE006:A1": "111"})
    text = render_room_plan("FE006", _venue(), plan, _students(), None, ["111"])

    assert "Zusätzlich" not in text


def test_redirects_name_the_room_the_person_sits_in():
    # Wer nach seinem Anfangsbuchstaben hierherkommt und sich auf der Karte
    # nicht findet, muss hier erfahren, wohin er stattdessen gehen soll.
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    text = render_room_plan(
        "FE006", _venue(), plan, _students(), "25INB: A-K", [], {"222": "GU101"}
    )

    assert "Nicht in diesem Raum: 22 (GU101)" in text
    assert "Berger" not in text


def test_no_redirect_line_without_redirects():
    plan = SeatingPlan(assignments={"FE006:A1": "111"})
    text = render_room_plan("FE006", _venue(), plan, _students(), "25INB: A-K", [], {})

    assert "Nicht in diesem Raum" not in text


def test_redirects_without_a_rule_stay_hidden():
    # Ohne Einteilung schickt niemanden ein Buchstabe an diese Tuer.
    plan = SeatingPlan(assignments={"GU101:A1": "222"})
    text = render_room_plan("FE006", _venue(), plan, _students(), None, [], {"222": "GU101"})

    assert "Nicht in diesem Raum" not in text


def test_both_directions_appear_together():
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    text = render_room_plan(
        "FE006", _venue(), plan, _students(), "25INB: A-K", ["111"], {"222": "GU101"}
    )

    zeilen = text.splitlines()
    assert any(z.startswith("Zusätzlich in diesem Raum") for z in zeilen)
    assert any(z.startswith("Nicht in diesem Raum") for z in zeilen)


def test_ambiguous_redirect_is_split_by_the_next_letter():
    # Zwei Prüflinge mit demselben Anzeigecode: Einer sitzt hier, der andere
    # wird von hier verwiesen. Der Buchstabenbereich der Einteilung trennt sie
    # nicht, ein Buchstabe mehr vom Nachnamen schon.
    students = _students()
    students["333"] = Student(
        matriculation_number="333",
        seminar_group="25INB-2",
        name="Conrad, Carla",
        display_code="11",
    )
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "333"})
    text = render_room_plan(
        "FE006", _venue(), plan, students, "25INB: A-K", [], {"333": "GU101"}
    )

    assert "Nicht in diesem Raum" not in text
    assert "Code 11 kommt zweimal vor" in text
    zeilen = [z.split() for z in text.splitlines() if z.startswith("    Nachname")]
    assert ["Nachname", "mit", "A", "hier"] in zeilen
    assert ["Nachname", "mit", "C", "GU101"] in zeilen
    # Weiter als nötig wird der Name nicht preisgegeben.
    assert "Albrecht" not in text and "Conrad" not in text
    assert "Aufsicht" not in text


def test_identical_surnames_fall_back_to_the_invigilator():
    # Gleicher Code und gleicher Nachname: Kein Präfix trennt die beiden.
    students = _students()
    students["333"] = Student(
        matriculation_number="333",
        seminar_group="25INB-2",
        name="Albrecht, Bert",
        display_code="11",
    )
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "333"})
    text = render_room_plan(
        "FE006", _venue(), plan, students, "25INB: A-K", [], {"333": "GU101"}
    )

    assert "Achtung, Code 11 kommt doppelt vor" in text
    assert "Aufsicht" in text
    assert "Nachname mit" not in text


def test_umlauts_are_folded_in_the_refinement():
    # Die Einteilung normiert Umlaute, die Verfeinerung muss dasselbe tun.
    students = _students()
    students["333"] = Student(
        matriculation_number="333",
        seminar_group="25INB-2",
        name="Öhler, Otto",
        display_code="11",
    )
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "333"})
    text = render_room_plan(
        "FE006", _venue(), plan, students, "25INB: A-K", [], {"333": "GU101"}
    )

    assert "Nachname mit O" in text
    assert "Ö" not in text


def test_unambiguous_redirect_stays_a_plain_pointer():
    # Gegenprobe: Ohne Codegleichheit bleibt es beim knappen Verweis.
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    text = render_room_plan(
        "FE006", _venue(), plan, _students(), "25INB: A-K", [], {"222": "GU101"}
    )

    assert "Nicht in diesem Raum: 22 (GU101)" in text
    assert "Achtung" not in text


def test_all_notices_also_land_in_one_file(tmp_path):
    # Gedruckt wird der Stapel in einem Vorgang, verteilt entlang der Seiten.
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    pfade = write_plans(_venue(), plan, _students(), tmp_path, formats=("pdf",))

    gesamt = tmp_path / "aushaenge.pdf"
    assert gesamt in pfade
    seiten = gesamt.read_bytes().count(b"/Type /Page ")
    einzeln = sum(
        (tmp_path / f"plan_{raum}.pdf").read_bytes().count(b"/Type /Page ")
        for raum in ("FE006", "GU101")
    )
    assert seiten == einzeln == 2


def test_each_notice_starts_on_its_own_page(tmp_path):
    # Fortlaufende Paginierung liesse zwei Aushaenge auf einer Seite enden,
    # und der Stapel waere nicht mehr entlang der Seiten zu trennen.
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    write_plans(_venue(), plan, _students(), tmp_path, formats=("pdf",))

    roh = (tmp_path / "aushaenge.pdf").read_bytes()
    assert roh.count(b"Aushangplan Raum FE006") == 1
    assert roh.count(b"Aushangplan Raum GU101") == 1


def test_the_lead_document_precedes_every_room_in_the_stack(tmp_path):
    # Einen gemeinsamen Eingang gibt es nicht. Jede Tuer bekommt deshalb ihr
    # eigenes Exemplar der Raumzuordnung, und zwar vor ihrem Aushangplan.
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    write_plans(
        _venue(),
        plan,
        _students(),
        tmp_path,
        formats=("pdf",),
        lead=["Raumzuordnung zur Prüfung", "A-K  FE006"],
    )

    roh = (tmp_path / "aushaenge.pdf").read_bytes()
    assert roh.count(b"/Type /Page ") == 4
    assert roh.count(b"Raumzuordnung") == 2
    erste = roh.index(b"Raumzuordnung")
    zweite = roh.index(b"Raumzuordnung", erste + 1)
    assert erste < roh.index(b"Aushangplan Raum FE006") < zweite
    assert zweite < roh.index(b"Aushangplan Raum GU101")


def test_the_single_notices_stay_without_the_lead(tmp_path):
    # Zum Nachdrucken einer einzelnen Tuer bleibt der Aushangplan fuer sich.
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    write_plans(
        _venue(),
        plan,
        _students(),
        tmp_path,
        formats=("pdf",),
        lead=["Raumzuordnung zur Prüfung", "A-K  FE006"],
    )

    einzeln = (tmp_path / "plan_FE006.pdf").read_bytes()
    assert b"Raumzuordnung" not in einzeln


def test_write_plans_passes_the_redirects_per_room(tmp_path):
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    write_plans(
        _venue(),
        plan,
        _students(),
        tmp_path,
        formats=("text",),
        rules={"FE006": "25INB: A-K", "GU101": "25MIB"},
        redirects={"FE006": {"222": "GU101"}},
    )

    mit = (tmp_path / "plan_FE006.txt").read_text(encoding="utf-8")
    ohne = (tmp_path / "plan_GU101.txt").read_text(encoding="utf-8")
    assert "Nicht in diesem Raum: 22 (GU101)" in mit
    assert "Nicht in diesem Raum" not in ohne


def test_write_plans_passes_the_exceptions_per_room(tmp_path):
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    write_plans(
        _venue(),
        plan,
        _students(),
        tmp_path,
        formats=("text",),
        rules={"FE006": "25INB: A-K", "GU101": "25MIB"},
        exceptions={"FE006": ["111"]},
    )

    mit = (tmp_path / "plan_FE006.txt").read_text(encoding="utf-8")
    ohne = (tmp_path / "plan_GU101.txt").read_text(encoding="utf-8")
    assert "Zusätzlich in diesem Raum" in mit
    assert "Zusätzlich" not in ohne


def _gap_venue():
    """Muster X.X X: Stuhl, leer zu lassender Stuhl, Stuhl, Gang, Stuhl."""
    room, seats = parse_room_grid("SR9", ["X.X X"])
    return Venue(rooms={"SR9": room}, seats=seats, neighbors=compute_neighbors(seats))


def test_blocked_chairs_are_drawn_but_aisles_are_not():
    # Wer vor der Karte steht, zaehlt Stuehle. Bliebe der leer zu lassende
    # Stuhl unsichtbar, zaehlte er anders, als die Karte zeigt. Der Gang
    # dagegen ist kein Stuhl und muss Zwischenraum bleiben.
    venue = _gap_venue()
    plan = SeatingPlan(assignments={sorted(venue.rooms["SR9"].seat_ids)[0]: "111"})
    text = render_room_plan("SR9", venue, plan, _students())

    assert _map_lines(text)[0] == " 11  .   -       -"


def test_single_character_markers_sit_in_the_middle_of_their_cell():
    # Rechtsbündig hing der Strich am rechten Zellenrand und damit neben dem
    # Stuhl, den er meint.
    venue = _gap_venue()
    plan = SeatingPlan(assignments={sorted(venue.rooms["SR9"].seat_ids)[0]: "111"})
    zeile = _map_lines(render_room_plan("SR9", venue, plan, _students()))[0]

    for marker in (".", "-"):
        stelle = zeile.index(marker)
        assert zeile[stelle - 1] == " "
        assert zeile[stelle + 1 : stelle + 2] in (" ", "")


def test_legend_names_every_marker_of_the_map():
    venue = _gap_venue()
    plan = SeatingPlan(assignments={sorted(venue.rooms["SR9"].seat_ids)[0]: "111"})
    text = render_room_plan("SR9", venue, plan, _students())

    assert "Stuhl bleibt leer" in text
    assert "Platz nicht vergeben" in text
    assert "Reserve" in text


def test_room_plan_marks_the_position_of_the_board():
    plan = SeatingPlan(assignments={"FE006:A1": "111"})
    text_rows = render_room_plan("FE006", _venue(), plan, _students()).splitlines()

    board = next(i for i, z in enumerate(text_rows) if BOARD in z)
    first_map = next(
        i for i, z in enumerate(text_rows) if i > board and z.strip()
    )
    # Die Tafel steht vor der ersten Sitzreihe, nicht dahinter.
    assert board < first_map


def test_room_plan_reproduces_the_room_layout():
    # Drei Plaetze in einer Reihe, ein Gang, zwei weitere: die Karte muss die
    # Luecke zeigen, sonst ist sie als Orientierung im Raum wertlos.
    room, seats = parse_room_grid("GU101", ["XXX XX"])
    venue = Venue(
        rooms={"GU101": room}, seats=seats, neighbors=compute_neighbors(seats)
    )
    plan = SeatingPlan(assignments={"GU101:A1": "111", "GU101:A5": "222"})
    seat_map = _map_lines(render_room_plan("GU101", venue, plan, _students()))

    assert len(seat_map) == 1
    fields = seat_map[0].split()
    assert fields == ["11", "-", "-", "-", "22"]


def test_room_plan_distinguishes_free_from_reserved_seats():
    venue = _venue(reserved=frozenset({"FE006:A3"}))
    plan = SeatingPlan(assignments={"FE006:A1": "111"})
    seat_map = _map_lines(render_room_plan("FE006", venue, plan, _students()))

    fields = seat_map[0].split()
    assert fields == ["11", EMPTY_MARKER, RESERVED_MARKER]


def test_room_plan_carries_the_rule_in_its_header():
    # Die Regel ist der eigentliche Aushang: Wer vor dem Raum steht, soll ohne
    # Suche in der Tabelle erkennen, ob er hier richtig ist.
    plan = SeatingPlan(assignments={"FE006:A1": "111"})
    text = render_room_plan("FE006", _venue(), plan, _students(), "23MIB+25INB: A-D")

    first_room = text.splitlines()[:5]
    assert any("23MIB+25INB: A-D" in line for line in first_room)


def test_room_plan_without_a_rule_keeps_the_header_unchanged():
    plan = SeatingPlan(assignments={"FE006:A1": "111"})
    baseline = render_room_plan("FE006", _venue(), plan, _students())
    empty = render_room_plan("FE006", _venue(), plan, _students(), None)

    assert baseline == empty
    assert "Zuordnung:" not in baseline


def test_write_plans_creates_one_file_per_room_and_format(tmp_path):
    plan = SeatingPlan(assignments={"FE006:A1": "111"})
    paths = write_plans(_venue(), plan, _students(), tmp_path)

    assert {p.name for p in paths} == {
        "plan_FE006.txt",
        "plan_FE006.pdf",
        "plan_GU101.txt",
        "plan_GU101.pdf",
        "aushaenge.pdf",
    }
    pdf = next(p for p in paths if p.suffix == ".pdf")
    assert pdf.read_bytes().startswith(b"%PDF")


def test_write_plans_passes_each_room_its_own_rule(tmp_path):
    plan = SeatingPlan(assignments={"FE006:A1": "111", "GU101:A1": "222"})
    write_plans(
        _venue(),
        plan,
        _students(),
        tmp_path,
        formats=("text",),
        rules={"FE006": "25INB: A-K", "GU101": "25MIB"},
    )

    assert "25INB: A-K" in (tmp_path / "plan_FE006.txt").read_text(encoding="utf-8")
    assert "25MIB" in (tmp_path / "plan_GU101.txt").read_text(encoding="utf-8")
    assert "25INB" not in (tmp_path / "plan_GU101.txt").read_text(encoding="utf-8")
