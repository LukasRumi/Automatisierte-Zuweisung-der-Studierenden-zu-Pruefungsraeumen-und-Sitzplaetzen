from pathlib import Path

from pruefung.algorithms.genetic import GAConfig, _is_better, genetic_assign
from pruefung.algorithms.greedy import greedy_assign
from pruefung.constraints import compute_neighbors, find_hard_violations, objective, Weights
from pruefung.models import Student, Venue
from pruefung.parsing.rooms import parse_room_grid
from pruefung.parsing.students import parse_students_csv
from pruefung.preprocessing import preprocess_students
from pruefung.venue import load_venue

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _venue(grid, radius=1.45):
    room, seats = parse_room_grid("R", grid)
    return Venue(rooms={"R": room}, seats=seats, neighbors=compute_neighbors(seats, radius=radius))


def _students(n, groups):
    return [
        Student(
            matriculation_number=str(1000 + i),
            seminar_group=groups[i % len(groups)],
        )
        for i in range(n)
    ]


def test_genetic_result_is_always_hard_constraint_feasible():
    venue = _venue(["XXXX", "XXXX", "XXXX"])
    students = _students(8, ["G1", "G2"])
    config = GAConfig(population_size=20, generations=15, seed=42)

    result = genetic_assign(students, venue, forced=None, weights=Weights(), config=config)
    students_by_id = {s.matriculation_number: s for s in students}

    assert find_hard_violations(result.plan, venue, students_by_id) == []
    assert len(result.plan.assignments) == len(students)


def test_genetic_is_reproducible_with_a_fixed_seed():
    venue = _venue(["XXXX", "XXXX"])
    students = _students(6, ["G1", "G2", "G3"])
    config = GAConfig(population_size=15, generations=10, seed=7)

    result_a = genetic_assign(students, venue, config=config)
    result_b = genetic_assign(students, venue, config=GAConfig(population_size=15, generations=10, seed=7))

    assert result_a.plan.assignments == result_b.plan.assignments
    assert result_a.best_cost == result_b.best_cost


def test_genetic_does_not_regress_compared_to_a_random_individual():
    venue = _venue(["XXXXXX", "XXXXXX", "XXXXXX"])
    students = _students(12, ["G1", "G2", "G3"])
    config = GAConfig(population_size=30, generations=40, seed=1)

    result = genetic_assign(students, venue, config=config)
    students_by_id = {s.matriculation_number: s for s in students}

    # Die Fitness ist lexikographisch (Verletzungen, Z); die Evolution darf sich
    # gegenüber ihrem Startindividuum nicht verschlechtern.
    start_violations, start_z = result.cost_history[0]
    end_violations, end_z = result.cost_history[-1]
    assert (end_violations, end_z) <= (start_violations, start_z)


def test_constructive_population_beats_a_purely_random_one():
    # Eine rein zufaellige Startpopulation laesst die Evolution stagnieren:
    # Die Rekombination zweier unbrauchbarer Individuen liefert nichts Brauchbares.
    venue = _venue(["XXXXXX", "XXXXXX", "XXXXXX"])
    students = _students(14, ["G1", "G2", "G3"])

    purely_random = genetic_assign(
        students, venue, config=GAConfig(population_size=30, generations=60, seed=5,
                                        constructive_share=0.0)
    )
    constructive = genetic_assign(
        students, venue, config=GAConfig(population_size=30, generations=60, seed=5,
                                         constructive_share=0.25)
    )
    assert len(constructive.plan.assignments) >= len(purely_random.plan.assignments)


def test_constructive_share_controls_the_initial_population():
    venue = _venue(["XXXX", "XXXX"])
    students = _students(6, ["G1", "G2"])
    # Beide Extremwerte muessen zulaessige Ergebnisse liefern.
    for share in (0.0, 1.0):
        result = genetic_assign(
            students, venue, config=GAConfig(population_size=10, generations=10, seed=1,
                                             constructive_share=share)
        )
        by_id = {s.matriculation_number: s for s in students}
        assert find_hard_violations(result.plan, venue, by_id) == []


def test_genetic_never_trades_a_hard_violation_for_lower_soft_cost():
    # Die Fitness ist lexikographisch: Ein Individuum mit weniger Verletzungen
    # gewinnt immer, egal wie hoch seine weichen Kosten sind.
    assert _is_better((0, 999999.0), (1, 0.0))
    assert not _is_better((1, 0.0), (0, 999999.0))
    # Bei gleicher Verletzungszahl entscheidet die Zielfunktion.
    assert _is_better((2, 10.0), (2, 20.0))


def test_genetic_seats_at_least_as_many_students_as_greedy_on_example_data():
    students, forced = parse_students_csv(EXAMPLES / "students.csv")
    students = preprocess_students(students)
    venue = load_venue(EXAMPLES / "rooms")

    greedy_plan = greedy_assign(students, venue, forced)
    config = GAConfig(population_size=40, generations=60, seed=3)
    result = genetic_assign(students, venue, forced, Weights(), config)

    students_by_id = {s.matriculation_number: s for s in students}
    assert find_hard_violations(result.plan, venue, students_by_id) == []
    assert len(result.plan.assignments) >= len(greedy_plan.assignments)
