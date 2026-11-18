"""Tests der vorgegebenen Platzzuweisungen aus F und der Umlautbehandlung.

Die Menge F war bis zuletzt ungeprueft, da die reale Teilnehmerliste keine
einzige Vorgabe enthaelt. Die Faelle hier sind daher konstruiert.
"""

import json

import pytest

from pruefung.algorithms.genetic import GAConfig, enforce_feasibility, repair_hard_violations
from pruefung.cli import main
from pruefung.constraints import (
    compute_neighbors,
    find_all_violations,
    find_forced_neighbor_pairs,
    find_hard_violations,
)
from pruefung.models import (
    ForcedAssignment,
    SeatingPlan,
    Student,
    Venue,
    normalise_letter,
    replace_student,
)
from pruefung.parsing.rooms import parse_room_grid
from pruefung.pipeline import assign
from pruefung.venue import load_venue

ALGORITHMS = ("greedy", "first-fit", "genetic")
SMALL_GA = GAConfig(population_size=20, generations=20, seed=3)


def _venue(grids: dict[str, list[str]], reserve: int = 0) -> Venue:
    rooms, seats = {}, {}
    for name, grid in grids.items():
        room, room_seats = parse_room_grid(name, grid)
        rooms[name] = room
        seats.update(room_seats)
    return Venue(rooms=rooms, seats=seats, neighbors=compute_neighbors(seats))


def _student(number: str, group: str, last_name: str) -> Student:
    return Student(
        matriculation_number=number,
        seminar_group=group,
        name=f"{last_name}, Vorname",
    )


def _cohort(count: int) -> list[Student]:
    return [
        _student(f"{100 + i}1", f"G{i % 2 + 1}", f"{chr(65 + i)}nachname")
        for i in range(count)
    ]


def test_forced_room_wins_over_the_assignment_rule():
    # Die Einteilung schickt einen Pruefling nach R2, die Vorgabe nach R1.
    # Die Vorgabe ist eine harte Restriktion und geht vor. Vorher brach der
    # Lauf hier mit "unbekannte Matrikelnummer" ab.
    venue = _venue({"R1": ["X.X.X.X", "X.X.X.X"], "R2": ["X.X.X.X", "X.X.X.X"]})
    people = _cohort(8) + [_student("9991", "G1", "Znachname")]
    forced = [ForcedAssignment(matriculation_number="9991", room="R1", seat_label="A1")]

    result = assign(people, venue, forced, algorithm="first-fit", room_assignment="rules")

    assert result.plan.assignments["R1:A1"] == "9991"


def _assert_everyone_finds_their_room(result, venue):
    """Wer nicht im Raum seiner Einteilung sitzt, steht dort als Verweis und
    im Sitzraum als Ausnahme. Sonst faende die Person ihren Platz nicht."""
    room_of = {m: venue.seats[seat].room for seat, m in result.plan.assignments.items()}
    exceptions = result.metrics["ausnahmen_je_raum"]
    redirects = result.metrics["verweise_je_raum"]
    for student in result.students:
        number = student.matriculation_number
        if number not in room_of:
            continue
        home = [room for room, rule in result.shown_rules.items() if rule.covers(student)]
        assert len(home) == 1
        if home[0] == room_of[number]:
            assert number not in exceptions.get(room_of[number], [])
        else:
            assert redirects[home[0]].get(number) == room_of[number]
            assert number in exceptions[room_of[number]]


@pytest.mark.parametrize("algorithm", ("greedy", "first-fit"))
@pytest.mark.parametrize("number, room, seat", [("9991", "R1", "A1"), ("1001", "R2", "A4")])
def test_a_fixed_seat_against_the_assignment_is_listed_on_both_posters(
    number, room, seat, algorithm
):
    # Vorher massen die Listen an der besten Regel je Raum statt an der
    # ausgehaengten Einteilung. Dann stand der Verweis nicht an der Tuer, an
    # die die Einteilung den Pruefling schickt, und er fand seinen Platz nicht.
    venue = _venue({"R1": ["X.X.X.X", "X.X.X.X"], "R2": ["X.X.X.X", "X.X.X.X"]})
    people = _cohort(8)
    if number == "9991":
        people.append(_student("9991", "G1", "Znachname"))
    forced = [ForcedAssignment(matriculation_number=number, room=room, seat_label=seat)]

    result = assign(people, venue, forced, algorithm=algorithm, room_assignment="rules")

    assert result.plan.assignments[f"{room}:{seat}"] == number
    _assert_everyone_finds_their_room(result, venue)


def test_the_console_names_both_counts(tmp_path, capsys):
    # Der feste Platz holt Anna aus dem Raum ihrer Einteilung. Der Aushang
    # nennt sie deshalb zweimal, als Verweis und als Ausnahme. E(x) misst an
    # der guenstigsten Einteilung je Raum und kommt mit weniger aus.
    liste = tmp_path / "liste.csv"
    zeilen = [
        f"10000{i + 1}1;G{i % 2 + 1};{chr(65 + i)}nachname, Vorname;"
        + ("R2:A4" if i == 0 else "")
        for i in range(8)
    ]
    liste.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    raeume = tmp_path / "raeume"
    raeume.mkdir()
    for name in ("R1", "R2"):
        (raeume / f"{name}.txt").write_text("X.X.X.X\nX.X.X.X\n", encoding="utf-8")
    out = tmp_path / "out"

    code = main([
        "assign",
        "--students", str(liste),
        "--rooms", str(raeume),
        "--output", str(out),
        "--algorithm", "greedy",
        "--room-assignment", "rules",
        "--format", "text",
        "--reserve-seats", "0",
    ])

    assert code == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    listed = sum(len(v) for v in report["ausnahmen_je_raum"].values()) + sum(
        len(v) for v in report["verweise_je_raum"].values()
    )
    assert report["aushang_eintraege"] == listed == 2
    assert report["ausnahmen"] < listed
    ausgabe = capsys.readouterr().out
    assert (
        f"Raumzuordnung: rules ({report['ausnahmen']} Ausnahmen, "
        "auf den Aushängen 2 Einträge)"
    ) in ausgabe


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_two_forced_neighbours_of_one_group_are_kept(algorithm):
    # Die Planung setzt zwei Prueflinge derselben Gruppe ausdruecklich
    # nebeneinander. Feste Plaetze gehen der Trennung vor. Gegenueber dem
    # dritten Pruefling der Gruppe gilt die Trennung weiter: A3 liegt im Radius
    # von A2, also bleibt ihm nur A4.
    venue = _venue({"R1": ["XX.XX"]})
    people = [
        _student("1111", "G1", "Anachname"),
        _student("2221", "G1", "Bnachname"),
        _student("3331", "G1", "Cnachname"),
    ]
    forced = [
        ForcedAssignment(matriculation_number="1111", room="R1", seat_label="A1"),
        ForcedAssignment(matriculation_number="2221", room="R1", seat_label="A2"),
    ]

    result = assign(people, venue, forced, algorithm=algorithm, ga_config=SMALL_GA)

    by_id = {s.matriculation_number: s for s in result.students}
    assert result.plan.assignments["R1:A1"] == "1111"
    assert result.plan.assignments["R1:A2"] == "2221"
    assert result.plan.seat_of("3331") == "R1:A4"
    assert find_all_violations(result.plan, venue, by_id) == []


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_three_forced_neighbours_of_one_group_are_kept(algorithm):
    # Die Trennung wird paarweise geprueft. Drei feste Plaetze derselben Gruppe
    # in einer Reihe ergeben drei Paare, die alle in F liegen und damit
    # erlaubt sind. Fuer den vierten Pruefling der Gruppe gilt die Trennung
    # weiter: A4 liegt im Radius von A3, also bleibt ihm nur A5.
    venue = _venue({"R1": ["XXX.X.X"]})
    people = [
        _student("1111", "G1", "Anachname"),
        _student("2221", "G1", "Bnachname"),
        _student("3331", "G1", "Cnachname"),
        _student("4441", "G1", "Dnachname"),
    ]
    forced = [
        ForcedAssignment(matriculation_number="1111", room="R1", seat_label="A1"),
        ForcedAssignment(matriculation_number="2221", room="R1", seat_label="A2"),
        ForcedAssignment(matriculation_number="3331", room="R1", seat_label="A3"),
    ]

    result = assign(people, venue, forced, algorithm=algorithm, ga_config=SMALL_GA)

    by_id = {s.matriculation_number: s for s in result.students}
    assert [result.plan.assignments[f"R1:A{i}"] for i in (1, 2, 3)] == ["1111", "2221", "3331"]
    assert result.plan.seat_of("4441") == "R1:A5"
    assert find_all_violations(result.plan, venue, by_id) == []
    assert find_forced_neighbor_pairs(result.plan, venue, by_id) == [
        ("R1:A1", "R1:A2"),
        ("R1:A1", "R1:A3"),
        ("R1:A2", "R1:A3"),
    ]


def test_repair_still_fixes_other_conflicts_next_to_a_forced_pair():
    # Das bewusst benachbarte Paar ist keine Verletzung. Vorher stand es als
    # erster Konflikt in der Liste, und die Reparatur gab dort auf, ohne den
    # echten Konflikt der Gruppe G2 anzugehen.
    venue = _venue({"R1": ["XX.XX"], "R2": ["XX.XX"]})
    pair = [
        replace_student(_student("1111", "G1", "Anachname"), fixed_seat="R1:A1"),
        replace_student(_student("2221", "G1", "Bnachname"), fixed_seat="R1:A2"),
    ]
    others = [_student("3331", "G2", "Cnachname"), _student("4441", "G2", "Dnachname")]
    by_id = {s.matriculation_number: s for s in pair + others}
    plan = SeatingPlan(
        {"R1:A1": "1111", "R1:A2": "2221", "R2:A1": "3331", "R2:A2": "4441"}
    )

    repaired = repair_hard_violations(plan, venue, by_id, fixed=frozenset({"R1:A1", "R1:A2"}))

    assert repaired.assignments["R1:A1"] == "1111"
    assert repaired.assignments["R1:A2"] == "2221"
    assert find_all_violations(repaired, venue, by_id) == []
    assert len(repaired.assignments) == 4


def test_genetic_keeps_a_forced_pair_and_separates_the_rest():
    venue = _venue({"R1": ["XX.XX"], "R2": ["XX.XX"]})
    people = [
        _student("1111", "G1", "Anachname"),
        _student("2221", "G1", "Bnachname"),
        _student("3331", "G1", "Cnachname"),
        _student("4441", "G2", "Dnachname"),
        _student("5551", "G2", "Enachname"),
    ]
    forced = [
        ForcedAssignment(matriculation_number="1111", room="R1", seat_label="A1"),
        ForcedAssignment(matriculation_number="2221", room="R1", seat_label="A2"),
    ]

    for seed in range(100):
        config = GAConfig(population_size=2, generations=1, seed=seed, constructive_share=0.0)
        result = assign(people, venue, forced, algorithm="genetic", ga_config=config)
        by_id = {s.matriculation_number: s for s in result.students}
        assert result.plan.assignments.get("R1:A1") == "1111", f"Saat {seed}"
        assert result.plan.assignments.get("R1:A2") == "2221", f"Saat {seed}"
        assert find_all_violations(result.plan, venue, by_id) == [], f"Saat {seed}"


def test_the_report_lists_a_forced_pair_instead_of_a_violation(tmp_path, capsys):
    liste = tmp_path / "liste.csv"
    liste.write_text(
        "1000011;G1;Albrecht, Anna;R1:A1\n"
        "1000021;G1;Berger, Ben;R1:A2\n"
        "1000031;G2;Conrad, Cem;\n",
        encoding="utf-8",
    )
    raeume = tmp_path / "raeume"
    raeume.mkdir()
    (raeume / "R1.txt").write_text("XX.XX\n", encoding="utf-8")
    out = tmp_path / "out"

    code = main([
        "assign",
        "--students", str(liste),
        "--rooms", str(raeume),
        "--output", str(out),
        "--algorithm", "first-fit",
        "--format", "text",
        "--reserve-seats", "0",
    ])

    assert code == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["vorgaben_nebeneinander"] == [["R1:A1", "R1:A2"]]
    assert report["harte_verletzungen"] == 0
    assert "R1:A1 und R1:A2" in capsys.readouterr().out


def test_two_seats_for_one_student_are_rejected():
    venue = _venue({"R1": ["X.X.X.X"]})
    people = [_student("1111", "G1", "Anachname")]
    forced = [
        ForcedAssignment(matriculation_number="1111", room="R1", seat_label="A1"),
        ForcedAssignment(matriculation_number="1111", room="R1", seat_label="A2"),
    ]

    with pytest.raises(ValueError, match="mehrere"):
        assign(people, venue, forced, algorithm="first-fit")


def test_a_reserved_seat_cannot_be_forced(tmp_path):
    (tmp_path / "R1.txt").write_text("X.X.X.X\n", encoding="utf-8")
    venue = load_venue(tmp_path, reserve_seats=1)
    reserved = sorted(venue.reserved)[0]
    room, label = reserved.split(":")
    people = [_student("1111", "G1", "Anachname")]
    forced = [ForcedAssignment(matriculation_number="1111", room=room, seat_label=label)]

    with pytest.raises(ValueError, match="Reserveplatz"):
        assign(people, venue, forced, algorithm="first-fit")


def test_two_forced_seats_with_the_same_code_in_one_room_are_rejected():
    # Beide Prueflinge tragen bei zwei Endziffern den Code "11". Ein Raum
    # koennte sie auf seinem Aushang nicht unterscheiden.
    venue = _venue({"R1": ["X.X.X"], "R2": ["X.X.X"]})
    people = [_student("1111", "G1", "Anachname"), _student("2111", "G2", "Bnachname")]
    seats = venue.assignable_in("R1")
    forced = [
        ForcedAssignment(matriculation_number="1111", room="R1", seat_label=seats[0].split(":")[1]),
        ForcedAssignment(matriculation_number="2111", room="R1", seat_label=seats[2].split(":")[1]),
    ]

    with pytest.raises(ValueError, match="Anzeigecode"):
        assign(people, venue, forced, algorithm="first-fit", code_length=2)


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_forced_assignment_keeps_the_plan_feasible(algorithm):
    venue = _venue({"R1": ["X.X.X.X", "X.X.X.X"]})
    people = _cohort(6)
    forced = [ForcedAssignment(matriculation_number="1001", room="R1", seat_label="A1")]

    result = assign(people, venue, forced, algorithm=algorithm, ga_config=SMALL_GA)

    by_id = {s.matriculation_number: s for s in result.students}
    assert find_hard_violations(result.plan, venue, by_id) == []
    assert result.plan.assignments["R1:A1"] == "1001"


def _fixed_seat_conflict():
    # Zwei Raeume mit je zwei benachbarten Plaetzen. Der Pruefling mit festem
    # Platz und ein zweiter seiner Gruppe sitzen nebeneinander.
    venue = _venue({"R1": ["XX"], "R2": ["XX"]})
    people = [
        _student("1001", "G1", "Fest"),
        _student("2001", "G1", "Sommer"),
        _student("3001", "G2", "Tal"),
        _student("4001", "G3", "Ufer"),
    ]
    return venue, people, venue.seats_in_reading_order()


def test_repair_never_moves_a_fixed_seat():
    # Vorher tauschte die Reparatur den Pruefling mit festem Platz nach R2.
    venue, people, seats = _fixed_seat_conflict()
    by_id = {s.matriculation_number: s for s in people}
    plan = SeatingPlan({seat: s.matriculation_number for seat, s in zip(seats, people)})

    repaired = repair_hard_violations(plan, venue, by_id, fixed=frozenset({seats[0]}))

    assert repaired.assignments[seats[0]] == "1001"
    assert find_all_violations(repaired, venue, by_id) == []


def test_enforce_feasibility_never_evicts_a_fixed_seat():
    # Der feste Platz liegt in der Mitte und ist an beiden Konflikten
    # beteiligt. Vorher wurde gerade er geraeumt.
    venue = _venue({"R1": ["X.X.X"]})
    people = [
        _student("1001", "G1", "Links"),
        _student("2001", "G1", "Fest"),
        _student("3001", "G1", "Rechts"),
    ]
    by_id = {s.matriculation_number: s for s in people}
    left, middle, right = venue.seats_in_reading_order()
    plan = SeatingPlan({left: "1001", middle: "2001", right: "3001"})

    result = enforce_feasibility(plan, venue, by_id, fixed=frozenset({middle}))

    assert result.assignments == {middle: "2001"}
    assert sorted(result.unassigned) == ["1001", "3001"]


def test_genetic_keeps_fixed_seats_after_repair():
    # Ein winziger GA ohne konstruktive Startindividuen endet oft mit einem
    # Konflikt am festen Platz. Die Nachbearbeitung darf ihn nicht aufloesen,
    # indem sie den vorgegebenen Pruefling versetzt.
    venue, people, seats = _fixed_seat_conflict()
    forced = [ForcedAssignment(matriculation_number="1001", room="R1", seat_label="A1")]

    for seed in range(200):
        config = GAConfig(population_size=2, generations=1, seed=seed, constructive_share=0.0)
        result = assign(people, venue, forced, algorithm="genetic", ga_config=config)
        by_id = {s.matriculation_number: s for s in result.students}
        assert result.plan.assignments.get(seats[0]) == "1001", f"Saat {seed}"
        assert find_all_violations(result.plan, venue, by_id) == []


@pytest.mark.parametrize(
    "char,expected",
    [("Ä", "A"), ("ä", "A"), ("Ö", "O"), ("Ü", "U"), ("ß", "S"), ("m", "M"), ("7", None)],
)
def test_umlauts_map_to_their_base_letter(char, expected):
    assert normalise_letter(char) == expected


def test_a_name_starting_with_an_umlaut_does_not_break_the_assignment():
    # Vorher scheiterte die einteilungsbasierte Zuordnung mit der irrefuehrenden
    # Meldung, die Kapazitaeten liessen sich nicht einhalten.
    venue = _venue({"R1": ["X.X.X.X", "X.X.X.X"], "R2": ["X.X.X.X", "X.X.X.X"]})
    people = _cohort(8) + [_student("8881", "G1", "Ähnlich")]

    result = assign(people, venue, [], algorithm="first-fit", room_assignment="rules")

    assert result.metrics["ausnahmen"] == 0
    assert "8881" in set(result.plan.assignments.values())
