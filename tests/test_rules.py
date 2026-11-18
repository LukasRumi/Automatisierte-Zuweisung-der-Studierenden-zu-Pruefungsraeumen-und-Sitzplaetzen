from pruefung.constraints import compute_neighbors
from pruefung.models import SeatingPlan, Student, Venue
from pruefung.parsing.rooms import parse_room_grid
from pruefung.rules import (
    Rule,
    best_rule_for_room,
    explainability_cost,
    render_rule,
    room_exceptions,
    room_redirects,
    room_rules,
    rule_length,
)


def _student(last_name: str, group: str, number: str) -> Student:
    return Student(matriculation_number=number, seminar_group=group, name=f"{last_name}, Vorname")


def _venue(size: int = 4):
    room_a, seats_a = parse_room_grid("GU101", ["X" * size])
    room_b, seats_b = parse_room_grid("FE006", ["X" * size])
    seats = {**seats_a, **seats_b}
    return Venue(
        rooms={"GU101": room_a, "FE006": room_b},
        seats=seats,
        neighbors=compute_neighbors(seats),
    )


def test_rule_covers_only_matching_group_and_letter_range():
    rule = Rule(frozenset({"25INB-1"}), "A", "K")
    assert rule.covers(_student("Bauer", "25INB-1", "1"))
    assert not rule.covers(_student("Zimmer", "25INB-1", "2"))  # Buchstabe außerhalb
    assert not rule.covers(_student("Bauer", "25MIB-1", "3"))  # falsche Gruppe


def test_student_without_a_name_is_covered_by_the_group_alone():
    rule = Rule(frozenset({"G1"}), "A", "K")
    without_names = Student(matriculation_number="1", seminar_group="G1")
    assert rule.covers(without_names)


def test_alphabetical_split_is_recognised_without_exceptions():
    # A-B in GU101, C-D in FE006: exakt durch Regeln beschreibbar.
    students = [
        _student("Albrecht", "G1", "1"),
        _student("Baumann", "G1", "2"),
        _student("Conrad", "G1", "3"),
        _student("Dietrich", "G1", "4"),
    ]
    venue = _venue(2)
    plan = SeatingPlan(
        assignments={"GU101:A1": "1", "GU101:A2": "2", "FE006:A1": "3", "FE006:A2": "4"}
    )
    assert explainability_cost(plan, venue, students) == 0


def test_group_split_is_recognised_without_exceptions():
    students = [
        _student("Albrecht", "25INB-1", "1"),
        _student("Zimmer", "25INB-1", "2"),
        _student("Bauer", "25MIB-1", "3"),
        _student("Yilmaz", "25MIB-1", "4"),
    ]
    venue = _venue(2)
    plan = SeatingPlan(
        assignments={"GU101:A1": "1", "GU101:A2": "2", "FE006:A1": "3", "FE006:A2": "4"}
    )
    assert explainability_cost(plan, venue, students) == 0


def test_room_exceptions_name_who_deviates():
    # Die blosse Anzahl genuegt nicht: Fuer den Aushang und den Report muss
    # feststehen, wer von der Einteilung abweicht.
    students = [
        _student("Albrecht", "G1", "1"),
        _student("Baumann", "G1", "2"),
        _student("Conrad", "G1", "3"),
        _student("Zimmer", "G1", "4"),
    ]
    venue = _venue(2)
    # Zimmer sitzt bei A und B statt bei C, weicht also ab.
    plan = SeatingPlan(
        assignments={"GU101:A1": "1", "GU101:A2": "4", "FE006:A1": "2", "FE006:A2": "3"}
    )

    deviating = room_exceptions(plan, venue, students)

    assert "4" in deviating["GU101"]
    assert explainability_cost(plan, venue, students) > 0


def _split_a_names():
    """Drei A-Namen, von denen einer im anderen Raum sitzt."""
    students = [
        _student("Albrecht", "G1", "1"),
        _student("Anders", "G1", "2"),
        _student("Arnold", "G1", "3"),
        _student("Zimmer", "G1", "4"),
    ]
    venue = _venue(2)
    plan = SeatingPlan(
        assignments={"GU101:A1": "1", "GU101:A2": "2", "FE006:A1": "3", "FE006:A2": "4"}
    )
    return students, venue, plan


def test_room_redirects_point_to_the_room_the_person_sits_in():
    # Arnold faellt unter die Einteilung von GU101, sitzt aber in FE006. Wer
    # dort nach dem Anfangsbuchstaben sucht, braucht an der Tuer von GU101
    # den Hinweis, wohin er stattdessen gehen muss.
    students, venue, plan = _split_a_names()

    verweise = room_redirects(plan, venue, students)

    assert verweise["GU101"] == {"3": "FE006"}
    assert verweise["FE006"] == {}


def test_both_directions_together_make_up_the_exception_count():
    # Die symmetrische Differenz zaehlt jede Abweichung zweimal, einmal als
    # Verweis beim Regelraum und einmal als Ausnahme beim Sitzraum.
    students, venue, plan = _split_a_names()

    ausnahmen = room_exceptions(plan, venue, students)
    verweise = room_redirects(plan, venue, students)

    zusammen = sum(len(v) for v in ausnahmen.values()) + sum(
        len(v) for v in verweise.values()
    )
    assert zusammen == explainability_cost(plan, venue, students)


def test_lists_follow_the_posted_assignment_even_for_an_empty_room():
    # Ausgehaengt ist A-Y in GU101 und Z in FE006, in FE006 sitzt aber
    # niemand. Zimmer sitzt in GU101. Die beste Regel fuer GU101 erfasst ihn,
    # misst man daran, faellt er durch beide Listen. Der Aushang nennt aber
    # FE006, also muss dort der Verweis stehen und in GU101 die Ausnahme.
    students = [
        _student("Albrecht", "G1", "1"),
        _student("Baumann", "G1", "2"),
        _student("Conrad", "G1", "3"),
        _student("Zimmer", "G1", "4"),
    ]
    venue = _venue(4)
    plan = SeatingPlan(
        assignments={"GU101:A1": "1", "GU101:A2": "2", "GU101:A3": "3", "GU101:A4": "4"}
    )
    shown = {
        "GU101": Rule(frozenset({"G1"}), "A", "Y"),
        "FE006": Rule(frozenset({"G1"}), "Z", "Z"),
    }

    assert room_exceptions(plan, venue, students) == {"GU101": []}
    assert room_exceptions(plan, venue, students, shown=shown) == {"GU101": ["4"], "FE006": []}
    assert room_redirects(plan, venue, students, shown=shown) == {
        "GU101": {},
        "FE006": {"4": "GU101"},
    }


def test_every_redirect_has_a_matching_exception_in_the_target_room():
    students, venue, plan = _split_a_names()

    ausnahmen = room_exceptions(plan, venue, students)
    for verweise in room_redirects(plan, venue, students).values():
        for number, ziel in verweise.items():
            assert number in ausnahmen[ziel]


def test_a_describable_assignment_has_no_named_exceptions():
    students = [
        _student("Albrecht", "G1", "1"),
        _student("Baumann", "G1", "2"),
        _student("Conrad", "G1", "3"),
        _student("Dietrich", "G1", "4"),
    ]
    venue = _venue(2)
    plan = SeatingPlan(
        assignments={"GU101:A1": "1", "GU101:A2": "2", "FE006:A1": "3", "FE006:A2": "4"}
    )

    deviating = room_exceptions(plan, venue, students)

    assert all(not names for names in deviating.values())


def test_scattered_assignment_produces_exceptions():
    # Gleiche Gruppe, Buchstaben über beide Räume verschränkt: nicht regelbeschreibbar.
    students = [
        _student("Albrecht", "G1", "1"),
        _student("Baumann", "G1", "2"),
        _student("Conrad", "G1", "3"),
        _student("Dietrich", "G1", "4"),
    ]
    venue = _venue(2)
    interleaved = SeatingPlan(
        assignments={"GU101:A1": "1", "GU101:A2": "3", "FE006:A1": "2", "FE006:A2": "4"}
    )
    assert explainability_cost(interleaved, venue, students) > 0


def test_broad_rule_is_penalised_by_students_outside_the_room():
    # Eine Regel, die auch Prüflinge außerhalb des Raumes abdeckt, ist falsch.
    # Ohne diese Gegenrechnung wäre "alle Gruppen, A-Z" immer ausnahmefrei.
    students = [
        _student("Albrecht", "G1", "1"),
        _student("Baumann", "G1", "2"),
    ]
    venue = _venue(2)
    plan = SeatingPlan(assignments={"GU101:A1": "1"})
    rule, costs = best_rule_for_room([students[0]], students)
    assert costs == 0
    assert not rule.covers(students[1])
    assert explainability_cost(plan, venue, students) == 0


def test_render_rule_collapses_sibling_groups_to_a_prefix():
    covers_all = {"25INB-1", "25INB-2", "25INB-3", "25MIB-1"}
    rule = Rule(frozenset({"25INB-1", "25INB-2", "25INB-3"}), "A", "D")
    assert render_rule(rule, covers_all) == "25INB: A-D"


def test_render_rule_without_letter_restriction_shows_groups_only():
    covers_all = {"25INB-1", "25MIB-1"}
    rule = Rule(frozenset({"25MIB-1"}), "A", "Z")
    assert render_rule(rule, covers_all) == "25MIB-1"


def test_render_rule_without_group_restriction_shows_letters_only():
    # Deckt die Regel alle Gruppen ab, trägt deren Aufzählung keine Information.
    # Übrig bleibt die Form "A-K", die auch die Aufgabenstellung nennt.
    covers_all = {"25INB-1", "25MIB-1"}
    rule = Rule(frozenset(covers_all), "A", "K")
    assert render_rule(rule, covers_all) == "A-K"


def test_render_rule_without_any_restriction_covers_everyone():
    covers_all = {"25INB-1", "25MIB-1"}
    rule = Rule(frozenset(covers_all), "A", "Z")
    assert render_rule(rule, covers_all) == "alle"


def test_rule_length_counts_what_the_notice_has_to_name():
    covers_all = {"25INB-1", "25INB-2", "25INB-3", "25MIB-1", "24INB-1"}
    # Vollstaendige Geschwisterschaft zaehlt als ein Name, da sie sich zum
    # Praefix zusammenfassen laesst.
    assert rule_length(Rule(frozenset({"25INB-1", "25INB-2", "25INB-3"}), "A", "Z"), covers_all) == 1
    # Unvollstaendige Geschwisterschaft muss jede Gruppe einzeln nennen.
    assert rule_length(Rule(frozenset({"25INB-1", "25INB-2"}), "A", "Z"), covers_all) == 2
    # Deckt die Regel alle Gruppen ab, nennt sie keine.
    assert rule_length(Rule(frozenset(covers_all), "A", "K"), covers_all) == 0


def test_rule_length_matches_the_rendered_notice():
    covers_all = {"25INB-1", "25INB-2", "25MIB-1", "24INB-1"}
    rule = Rule(frozenset({"25INB-1", "25INB-2", "24INB-1"}), "A", "K")
    rendered = render_rule(rule, covers_all).split(":")[0]
    assert rule_length(rule, covers_all) == len(rendered.split("+"))


def test_nta_room_is_exempt_from_the_measure():
    # Conrad und Cohn sind über Gruppe und Anfangsbuchstabe nicht unterscheidbar.
    # Sitzt einer von beiden im NTA-Raum, ist keine Regel ausnahmefrei möglich –
    # obwohl die Belegung des NTA-Raumes ihrer eigenen, klaren Regel folgt.
    students = [
        _student("Conrad", "G1", "1"),
        Student(matriculation_number="2", seminar_group="G1", name="Cohn, C", accommodation="NTA"),
    ]
    venue = _venue(2)
    plan = SeatingPlan(assignments={"GU101:A1": "1", "FE006:A1": "2"})

    # Ohne Ausnahmeregelung schlägt der NTA-Raum als Ausnahme zu Buche.
    assert explainability_cost(plan, venue, students) > 0
    # Als NTA-Raum deklariert zählt er nicht mit, und der reguläre Raum wird
    # gegen die um NTA bereinigte Grundgesamtheit bewertet.
    assert explainability_cost(plan, venue, students, nta_rooms=["FE006"]) == 0
    assert room_rules(plan, venue, students, nta_rooms=["FE006"])["FE006"] == (None, 0)


def test_unassigned_students_do_not_count_as_exceptions():
    # Baumann bekommt keinen Platz. Die Regel für GU101 beschreibt die
    # tatsächliche Belegung weiterhin exakt, also null Ausnahmen.
    students = [
        _student("Albrecht", "G1", "1"),
        _student("Baumann", "G1", "2"),
    ]
    venue = _venue(2)
    plan = SeatingPlan(assignments={"GU101:A1": "1"}, unassigned=["2"])
    assert explainability_cost(plan, venue, students) == 0


def test_room_rules_returns_one_rule_per_occupied_room():
    students = [_student("Albrecht", "G1", "1"), _student("Zimmer", "G2", "2")]
    venue = _venue(2)
    plan = SeatingPlan(assignments={"GU101:A1": "1", "FE006:A1": "2"})
    rule_by_room = room_rules(plan, venue, students)
    assert set(rule_by_room) == {"GU101", "FE006"}
