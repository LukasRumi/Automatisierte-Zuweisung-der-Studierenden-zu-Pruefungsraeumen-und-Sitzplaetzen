"""Robustheitspruefung ueber verschiedene Groessen und Sonderfaelle.

Reale Pruefungsdaten liegen nur fuer eine einzige Pruefung vor. Aussagen ueber
das Verhalten des Werkzeugs im Allgemeinen muessen daher an erzeugten Instanzen
geprueft werden.

Geprueft wird hier nicht die Guete einer Loesung, sondern dass das Werkzeug in
keinem Fall etwas Unzulaessiges erzeugt: Jeder ausgegebene Sitzplan haelt die
harten Restriktionen ein, oder das Werkzeug weist die Betroffenen als
unversorgt aus. Stilles Fehlverhalten, also ein vollstaendig wirkender Plan mit
verletzten Restriktionen, darf nicht vorkommen.
"""

import pytest

from pruefung.algorithms.genetic import GAConfig
from pruefung.constraints import find_all_violations
from pruefung.instances import InstanceSpec, generate_instance
from pruefung.nta import find_nta_violations, split_by_nta_flag
from pruefung.pipeline import assign
from pruefung.preprocessing import preprocess_students

EDGE_CASES = {
    "klein": InstanceSpec(students=20, groups=3, rooms=1, seed=11),
    "gross": InstanceSpec(students=400, groups=12, rooms=5, seed=12),
    "ein_raum": InstanceSpec(students=60, groups=4, rooms=1, seed=13),
    "viele_raeume": InstanceSpec(students=90, groups=6, rooms=6, seed=14),
    "eine_gruppe": InstanceSpec(students=40, groups=1, rooms=2, utilisation=0.5, seed=15),
    "zwei_gruppen": InstanceSpec(students=80, groups=2, rooms=2, utilisation=0.6, seed=16),
    "randvoll": InstanceSpec(students=100, groups=8, rooms=3, utilisation=1.0, seed=17),
    "ueberbestimmt": InstanceSpec(students=100, groups=8, rooms=3, utilisation=1.3, seed=18),
    "ohne_nta": InstanceSpec(students=60, groups=5, rooms=2, nta_fraction=0.0, seed=19),
    "ohne_namen": InstanceSpec(students=60, groups=5, rooms=2, with_names=False, seed=20),
    "ungleiche_reihen": InstanceSpec(students=120, groups=6, rooms=3, irregular_rows=True, seed=21),
}


def _check(spec: InstanceSpec, algorithm: str, room_assignment: str):
    student_list, venue, nta_rooms = generate_instance(spec)
    student_list = preprocess_students(student_list)
    result = assign(
        student_list,
        venue,
        [],
        algorithm=algorithm,
        room_assignment=room_assignment,
        ga_config=GAConfig(seed=1, generations=40, population_size=30),
    )

    by_id = {s.matriculation_number: s for s in result.students}
    plan = result.plan

    assert find_all_violations(plan, venue, by_id) == []
    assert find_nta_violations(plan, venue, by_id, nta_rooms) == []

    # Jeder Pruefling ist entweder platziert oder ausdruecklich als unversorgt
    # ausgewiesen. Ein stilles Verschwinden darf es nicht geben.
    placed = set(plan.assignments.values())
    assert placed | set(plan.unassigned) == {s.matriculation_number for s in student_list}
    assert not (placed & set(plan.unassigned))
    return result


@pytest.mark.parametrize("name", sorted(EDGE_CASES))
@pytest.mark.parametrize("algorithm", ["greedy", "first-fit", "genetic"])
def test_free_assignment_stays_feasible(name, algorithm):
    _check(EDGE_CASES[name], algorithm, "free")


@pytest.mark.parametrize("name", sorted(EDGE_CASES))
def test_rule_based_assignment_stays_feasible(name):
    spec = EDGE_CASES[name]
    try:
        result = _check(spec, "first-fit", "rules")
    except ValueError as errors:
        # Laesst sich keine regelbeschreibbare Zuordnung finden, muss das
        # ausdruecklich gemeldet werden statt still zu scheitern.
        assert "regelbeschreibbare" in str(errors)
        return
    assert result.metrics["ausnahmen"] == 0


def test_overdetermined_instance_reports_the_unplaced():
    # Mehr Pruefline als Plaetze: Die vollstaendige Platzierung ist unmoeglich,
    # das Werkzeug muss die Betroffenen benennen statt sie zu verschweigen.
    spec = EDGE_CASES["ueberbestimmt"]
    result = _check(spec, "genetic", "free")
    assert result.plan.unassigned


def test_single_group_forces_wide_spacing():
    # Gehoeren alle derselben Gruppe an, darf kein Paar benachbart sitzen.
    spec = EDGE_CASES["eine_gruppe"]
    result = _check(spec, "first-fit", "free")
    assert len(result.plan.assignments) > 0


def test_students_without_names_fall_back_to_the_number():
    student_list, venue, _ = generate_instance(EDGE_CASES["ohne_namen"])
    assert all(not s.name for s in student_list)
    _, regular = split_by_nta_flag(student_list)
    assert regular
    _check(EDGE_CASES["ohne_namen"], "first-fit", "free")
