"""Fortgeschrittenes Optimierungsverfahren: ein Genetischer Algorithmus (GA).

Kodierung (siehe Abschnitt 4.6 der Arbeit):

Ein Chromosom ist eine Permutation der noch freien (nicht durch F
vorgegebenen) Studierenden, aufgefüllt mit "Leerplatz"-Platzhaltern auf die
Anzahl der noch freien Sitzplätze. Position i des Chromosoms entspricht dem
i-ten freien Sitzplatz in Lesereihenfolge. Diese Kodierung garantiert, dass
Kapazitäts- und Eindeutigkeits-Restriktionen (jeder Platz höchstens einmal,
jeder Studierende genau einmal) durch Konstruktion nie verletzt werden.

Die Trennung von Seminargruppen, die Eindeutigkeit der Anzeigecodes und die
Raumvorgaben lassen sich nicht über die Kodierung erzwingen, da sie von der
räumlichen Anordnung abhängen. Sie gehen daher als erste Komponente in eine
lexikographische Fitness ein (siehe ``Fitness``). Nach dem Ende der Evolution beseitigt eine
lokale Reparatur (`repair_hard_violations`) verbliebene Konflikte; was sie
nicht auflösen kann, räumt `enforce_feasibility`, sodass das Ergebnis
ausnahmslos zulässig ist. Die durch F vorgegebenen Plätze lassen beide
Schritte unberührt.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from pruefung.algorithms.first_fit import first_fit_assign
from pruefung.algorithms.greedy import apply_forced_assignments
from pruefung.constraints import (
    Weights,
    find_all_violations,
    objective,
    seat_conflicts,
    with_fixed_seats,
)
from pruefung.models import ForcedAssignment, SeatingPlan, Student, Venue

_EMPTY_PREFIX = "__EMPTY_"


@dataclass(slots=True)
class GAConfig:
    """Hyperparameter des genetischen Algorithmus."""

    population_size: int = 100
    generations: int = 200
    mutation_rate: float = 0.05
    tournament_size: int = 3
    elitism: int = 2
    patience: int = 40
    """Abbruch, wenn sich die beste Fitness über so viele Generationen nicht verbessert."""
    seed: int | None = None
    constructive_share: float = 0.25
    """Anteil der Startpopulation, der konstruktiv erzeugt wird (Rest: Zufallspermutationen).

    Eine rein zufällige Startpopulation ist auf diesem Problem unbrauchbar: Ein
    zufälliger Sitzplan verletzt derart viele Restriktionen, dass die
    Rekombination zweier solcher Individuen wenig Verwertbares hervorbringt.
    Auf der realen Instanz senkt die Evolution die Zahl der Verletzungen dann
    zwar etwa auf die Hälfte, findet aber keinen zulässigen Plan, sodass alles
    an der Reparatur hängt. Ein einzelnes
    gutes Startindividuum genügt ebenfalls nicht -- es gewinnt zwar jedes
    Turnier, findet aber keine Partner, mit denen sich die Rekombination lohnt.

    Erzeugt werden die konstruktiven Individuen per First-Fit mit jeweils
    zufällig vertauschter Bearbeitungsreihenfolge, was unterschiedliche, aber
    durchweg brauchbare Lösungen liefert."""


Fitness = tuple[int, float]
"""Bewertung eines Individuums als Paar (Anzahl harter Verletzungen, Zielfunktion Z).

Der Vergleich erfolgt lexikographisch: Erst entscheidet die Zahl der verletzten
harten Restriktionen, nur bei Gleichstand die weichen Kosten. Ein einzelner
Strafterm wäre hier ungeeignet, weil sein Gewicht gegen die Größenordnung von Z
abgewogen werden müsste -- ist es zu klein, tauscht die Evolution Verletzungen
gegen weiche Verbesserungen ein. Die lexikographische Ordnung macht harte
Restriktionen unverhandelbar, ohne einen solchen Faktor zu benötigen.
"""


@dataclass(slots=True)
class GAResult:
    plan: SeatingPlan
    best_cost: float
    """Zielfunktion Z des Ergebnisses."""
    generations_run: int
    cost_history: list[list] = field(default_factory=list)
    """Verlauf der besten Fitness je Generation als ``[Verletzungen, Z]``."""


def _order_crossover(parent1: list[str], parent2: list[str], rng: random.Random) -> list[str]:
    n = len(parent1)
    if n < 2:
        return list(parent1)
    i, j = sorted(rng.sample(range(n), 2))
    child: list[str | None] = [None] * n
    child[i : j + 1] = parent1[i : j + 1]
    taken = set(child[i : j + 1])
    fill_values = (gene for gene in parent2 if gene not in taken)
    for k in range(n):
        if child[k] is None:
            child[k] = next(fill_values)
    return child  # type: ignore[return-value]


def _mutate(individual: list[str], mutation_rate: float, rng: random.Random) -> None:
    n = len(individual)
    for position in range(n):
        if rng.random() < mutation_rate:
            other = rng.randrange(n)
            individual[position], individual[other] = individual[other], individual[position]


def _is_better(candidate: Fitness, current: Fitness) -> bool:
    """Lexikographischer Vergleich zweier Fitnesswerte.

    Die Toleranz greift nur auf der zweiten Komponente, um Rundungsrauschen in
    der Zielfunktion nicht als Verbesserung zu werten.
    """
    if candidate[0] != current[0]:
        return candidate[0] < current[0]
    return candidate[1] < current[1] - 1e-9


def _tournament_select(
    ranked: list[tuple[list[str], Fitness]], size: int, rng: random.Random
) -> list[str]:
    sample_size = min(size, len(ranked))
    sample = rng.sample(ranked, sample_size)
    return min(sample, key=lambda pair: pair[1])[0]


def repair_hard_violations(
    plan: SeatingPlan,
    venue: Venue,
    students_by_id: dict[str, Student],
    max_rounds: int = 500,
    fixed: frozenset[str] = frozenset(),
) -> SeatingPlan:
    """Beseitigt verbleibende harte Verletzungen durch gezieltes Tauschen.

    Für jeden gefundenen Konflikt wird zunächst versucht, den betroffenen
    Studierenden mit einem anderen besetzten Platz zu tauschen; gelingt das
    nicht, wird ein freier, konfliktfreier Platz gesucht. Bei einer verletzten
    Raumvorgabe ist der betroffene Studierende derjenige, der außerhalb seines
    Raumes sitzt, sodass beide Schritte ihn in seinen Raum zurückholen. Die Suche ist auf
    ``max_rounds`` Durchläufe begrenzt, um bei überbestimmten Instanzen eine
    Terminierung zu garantieren; verbleibende Konflikte werden vom Aufrufer
    (siehe Ausgabe-Report) ausgewiesen.

    ``fixed`` enthält die durch $F$ vorgegebenen Plätze. Ihre Prüflinge werden
    weder getauscht noch versetzt. Liegt ein Konflikt an einem solchen Platz,
    weicht der andere Beteiligte aus.
    """
    plan = plan.copy()
    for _ in range(max_rounds):
        violations = find_all_violations(plan, venue, students_by_id)
        if not violations:
            break
        seat_a, seat_b = violations[0]
        if seat_a in fixed:
            seat_a, seat_b = seat_b, seat_a
        if seat_a in fixed:
            # Beide Plätze sind vorgegeben. Solche Vorgaben weist
            # ``apply_forced_assignments`` schon vor dem Lauf zurück.
            break
        occupant_a = plan.assignments[seat_a]
        student_a = students_by_id[occupant_a]
        resolved = False

        for candidate_seat, candidate_occupant in list(plan.assignments.items()):
            if candidate_seat in (seat_a, seat_b) or candidate_seat in fixed:
                continue
            plan.assignments[seat_a], plan.assignments[candidate_seat] = (
                candidate_occupant,
                occupant_a,
            )
            conflict_remains = seat_conflicts(
                seat_a, students_by_id[candidate_occupant], plan, students_by_id, venue
            ) or seat_conflicts(candidate_seat, student_a, plan, students_by_id, venue)
            if not conflict_remains:
                resolved = True
                break
            plan.assignments[seat_a], plan.assignments[candidate_seat] = (
                occupant_a,
                candidate_occupant,
            )

        if not resolved:
            del plan.assignments[seat_a]
            for empty_seat in venue.seats_in_reading_order():
                if empty_seat in plan.assignments:
                    continue
                if not seat_conflicts(empty_seat, student_a, plan, students_by_id, venue):
                    plan.assignments[empty_seat] = occupant_a
                    resolved = True
                    break
            if not resolved:
                plan.assignments[seat_a] = occupant_a
                break

    return plan


def enforce_feasibility(
    plan: SeatingPlan,
    venue: Venue,
    students_by_id: dict[str, Student],
    fixed: frozenset[str] = frozenset(),
) -> SeatingPlan:
    """Erzwingt die Einhaltung der harten Platzierungsrestriktionen im Ergebnis.

    Lässt die Reparatur bei einer überbestimmten Instanz Konflikte zurück, wird
    wiederholt derjenige Platz geräumt, der an den meisten Konflikten beteiligt
    ist. Die betroffenen Studierenden gelten anschließend als nicht zugewiesen.
    Ein unversorgter Prüfling weist die Planung auf fehlende Kapazität hin,
    während ein Sitzplan mit verletztem Sicherheitsabstand unbrauchbar wäre.

    Die durch $F$ vorgegebenen Plätze in ``fixed`` werden nie geräumt.
    """
    plan = plan.copy()
    while True:
        violations = find_all_violations(plan, venue, students_by_id)
        if not violations:
            return plan
        involved = Counter(
            seat_id for pair in violations for seat_id in pair if seat_id not in fixed
        )
        if not involved:
            # Nur noch Konflikte zwischen vorgegebenen Plätzen. Solche Vorgaben
            # weist ``apply_forced_assignments`` schon vor dem Lauf zurück.
            return plan
        worst = max(involved, key=lambda seat_id: (involved[seat_id], seat_id))
        plan.unassigned.append(plan.assignments.pop(worst))


def genetic_assign(
    students: list[Student],
    venue: Venue,
    forced: list[ForcedAssignment] | None = None,
    weights: Weights | None = None,
    config: GAConfig | None = None,
) -> GAResult:
    """Erzeugt einen Sitzplan mittels eines Genetischen Algorithmus."""
    weights = weights or Weights()
    config = config or GAConfig()
    rng = random.Random(config.seed)

    # Mit vermerktem festen Platz, damit die Bewertung ein Paar, das F
    # ausdrücklich nebeneinander setzt, nicht als Verletzung zählt.
    students_by_id = {
        s.matriculation_number: s for s in with_fixed_seats(students, forced or [])
    }
    base_plan = apply_forced_assignments(forced or [], students_by_id, venue)

    free_seats = [
        seat_id for seat_id in venue.seats_in_reading_order() if seat_id not in base_plan.assignments
    ]
    already_seated = set(base_plan.assignments.values())
    free_students = [s for s in students if s.matriculation_number not in already_seated]

    # Reichen die Plätze nicht aus, enthält das Chromosom mehr Gene als es
    # Plätze gibt. Die überzähligen Prüflinge bleiben dann unversorgt, statt
    # dass das Verfahren die Arbeit verweigert: Ein benannter Fehlschlag ist
    # für die Planung verwertbar, ein Abbruch nicht.
    num_dummies = max(0, len(free_seats) - len(free_students))
    dummy_ids = [f"{_EMPTY_PREFIX}{i}__" for i in range(num_dummies)]
    gene_pool = [s.matriculation_number for s in free_students] + dummy_ids

    def decode(individual: list[str]) -> SeatingPlan:
        plan = base_plan.copy()
        for seat_id, gene in zip(free_seats, individual):
            if not gene.startswith(_EMPTY_PREFIX):
                plan.assignments[seat_id] = gene
        for gene in individual[len(free_seats) :]:
            if not gene.startswith(_EMPTY_PREFIX):
                plan.unassigned.append(gene)
        return plan

    def cost(individual: list[str]) -> Fitness:
        plan = decode(individual)
        violations = len(find_all_violations(plan, venue, students_by_id))
        return violations, objective(plan, venue, students_by_id, weights)

    if not gene_pool:
        # Keine freien Studierenden/Plätze übrig (z. B. alles über F vorgegeben).
        return GAResult(plan=base_plan, best_cost=objective(base_plan, venue, students_by_id, weights), generations_run=0)

    free_seat_set = set(free_seats)

    def to_chromosome(plan: SeatingPlan) -> list[str]:
        """Übersetzt einen Sitzplan in eine Permutation über dem Genpool.

        Plätze, die der Plan nicht belegt, erhalten die übrigen Gene in
        zufälliger Reihenfolge -- das betrifft die Leerplatz-Platzhalter und
        etwaige vom Verfahren nicht versorgte Studierende.
        """
        occupied = {
            seat_id: matriculation_number
            for seat_id, matriculation_number in plan.assignments.items()
            if seat_id in free_seat_set
        }
        rest = [gene for gene in gene_pool if gene not in set(occupied.values())]
        rng.shuffle(rest)
        rest_iter = iter(rest)
        chromosome = [
            occupied[seat_id] if seat_id in occupied else next(rest_iter) for seat_id in free_seats
        ]
        # Gibt es mehr Gene als Plätze, hängen die überzähligen hinten an. Sie
        # nehmen an Rekombination und Mutation teil, werden aber nicht platziert.
        chromosome.extend(rest_iter)
        return chromosome

    population: list[list[str]] = []
    constructive_count = min(
        config.population_size, round(config.population_size * config.constructive_share)
    )
    for _ in range(constructive_count):
        sequence = list(free_students)
        rng.shuffle(sequence)
        population.append(
            to_chromosome(first_fit_assign(students, venue, forced, order=sequence))
        )

    while len(population) < config.population_size:
        individual = gene_pool[:]
        rng.shuffle(individual)
        population.append(individual)

    costs = [cost(ind) for ind in population]
    best_cost = min(costs)
    best_individual = population[costs.index(best_cost)]
    cost_history = [list(best_cost)]
    stale_generations = 0
    # Bricht die Schleife wegen Stagnation ab, wurde die angefangene Generation
    # nicht mehr durchlaufen. Gezählt wird deshalb erst am Ende des Rumpfes.
    completed_generations = 0

    for generation in range(1, config.generations + 1):
        if stale_generations >= config.patience:
            break

        ranked = sorted(zip(population, costs), key=lambda pair: pair[1])
        next_population = [ind for ind, _ in ranked[: config.elitism]]

        while len(next_population) < config.population_size:
            parent1 = _tournament_select(ranked, config.tournament_size, rng)
            parent2 = _tournament_select(ranked, config.tournament_size, rng)
            child = _order_crossover(parent1, parent2, rng)
            _mutate(child, config.mutation_rate, rng)
            next_population.append(child)

        population = next_population
        costs = [cost(ind) for ind in population]
        generation_best = min(costs)

        if _is_better(generation_best, best_cost):
            best_cost = generation_best
            best_individual = population[costs.index(generation_best)]
            stale_generations = 0
        else:
            stale_generations += 1

        cost_history.append(list(best_cost))
        completed_generations = generation

    final_plan = decode(best_individual)
    # Die Vorgaben aus F nehmen an der Evolution nicht teil. Auch die
    # Nachbearbeitung darf sie nicht versetzen oder räumen.
    fixed_seats = frozenset(base_plan.assignments)
    final_plan = repair_hard_violations(final_plan, venue, students_by_id, fixed=fixed_seats)
    final_plan = enforce_feasibility(final_plan, venue, students_by_id, fixed=fixed_seats)
    final_cost = objective(final_plan, venue, students_by_id, weights)

    return GAResult(
        plan=final_plan,
        best_cost=final_cost,
        generations_run=completed_generations,
        cost_history=cost_history,
    )
