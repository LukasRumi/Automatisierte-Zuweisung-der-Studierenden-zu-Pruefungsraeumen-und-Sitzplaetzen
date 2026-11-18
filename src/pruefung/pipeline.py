"""Orchestrierung eines vollständigen Zuweisungslaufs.

Der Lauf zerfällt in zwei Teilprobleme, die sich aus der harten
Raumrestriktion für Nachteilsausgleiche ergeben (siehe ``pruefung.nta``):

1. Studierende mit NTA-Vermerk werden ausschließlich im NTA-Raum platziert.
   Dies geschieht stets über die Greedy-Heuristik, da diese die Plätze in
   Lesereihenfolge vergibt und die Belegung damit an den vordersten Reihen
   beginnt.
2. Alle übrigen Studierenden werden mit dem gewählten Algorithmus auf die
   verbleibenden Räume verteilt; der NTA-Raum steht ihnen nicht zur Verfügung.

Beide Teillösungen werden anschließend zu einem Gesamtsitzplan vereinigt.

Raumvorgaben werden vorab aufgelöst (siehe ``pruefung.requirements``) und von
allen Verfahren über ``seat_conflicts`` eingehalten. Bei einteilungsbasierter
Raumzuordnung gehen sie, wie die festen Plätze, der Einteilung vor.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from pruefung.algorithms.genetic import GAConfig, genetic_assign
from pruefung.algorithms.greedy import greedy_assign
from pruefung.constraints import Weights, with_fixed_seats
from pruefung.models import ForcedAssignment, SeatingPlan, Student, Venue
from pruefung.nta import NTA_FLAG, find_nta_rooms, split_by_nta_flag, subvenue
from pruefung.preprocessing import (
    DEFAULT_CODE_LENGTHS,
    apply_code_length,
    code_multiplicities,
    minimal_code_length,
)
from pruefung.algorithms.first_fit import first_fit_assign
from pruefung.room_assignment import (
    candidate_room_plans,
    fill_with_exceptions,
    plan_rule_length,
)
from pruefung.requirements import ineffective_notes, resolve_room_requirements
from pruefung.rules import (
    Rule,
    explainability_cost,
    render_rule,
    room_exceptions,
    room_redirects,
)

ALGORITHMS = ("greedy", "first-fit", "genetic")
"""Wählbare Verfahren für die Sitzplatzvergabe.

``greedy`` und ``first-fit`` sind die beiden konstruktiven Varianten aus
Abschnitt 4.5 der Arbeit; sie unterscheiden sich darin, ob der Durchlauf über
die Sitzplätze oder über die Studierenden erfolgt.
"""


def _constructive_or_ga(
    students: list[Student],
    venue: Venue,
    forced: list[ForcedAssignment],
    *,
    algorithm: str,
    weights: Weights,
    ga_config: GAConfig | None,
) -> tuple[SeatingPlan, dict]:
    """Führt das gewählte Verfahren aus und liefert Plan samt Kennzahlen."""
    if algorithm == "greedy":
        return greedy_assign(students, venue, forced), {}
    if algorithm == "first-fit":
        return first_fit_assign(students, venue, forced), {}
    result = genetic_assign(students, venue, forced, weights, ga_config or GAConfig())
    return result.plan, {
        "generationen_durchlaufen": result.generations_run,
        "kostenverlauf": result.cost_history,
    }


@dataclass(slots=True)
class AssignmentResult:
    plan: SeatingPlan
    students: list[Student]
    """Die Studierenden mit gesetztem Anzeigecode, wie er dem Lauf zugrunde lag."""
    code_length: int
    nta_rooms: list[str]
    metrics: dict = field(default_factory=dict)
    shown_rules: dict[str, Rule] = field(default_factory=dict)
    """Die ausgehängte Einteilung je Raum. Leer bei freier Raumzuordnung."""


def _alternate(first: list, second: list, count: int) -> list:
    """Zieht abwechselnd aus zwei Ordnungen derselben Elemente, ohne Wiederholung.

    So kommen beide Ordnungskriterien in der Vorauswahl zum Zuge, ohne dass die
    Zahl der ausgewerteten Kandidaten steigt.
    """
    chosen: list = []
    seen: set[int] = set()
    for left, right in zip(first, second):
        for candidate in (left, right):
            if len(chosen) >= count:
                return chosen
            if id(candidate) not in seen:
                seen.add(id(candidate))
                chosen.append(candidate)
    return chosen


def _respect_forced_rooms(
    rooms: dict[str, list[Student]], forced_room: dict[str, str]
) -> dict[str, list[Student]]:
    """Verschiebt Prüflinge mit Platz- oder Raumvorgabe in den vorgegebenen Raum.

    Die Vorgaben sind eine harte Restriktion und gehen der Einteilung vor.
    Ohne diese Verschiebung erhielte die zweite Stufe eine Vorgabe für einen
    Prüfling, der ihrem Raum gar nicht zugeordnet ist. Bei einem festen Platz
    bräche sie ab, bei einer Raumvorgabe bliebe der Prüfling unversorgt.
    Wer entgegen seiner Einteilung platziert wird, erzeugt dort eine Ausnahme.
    Das ist der sachlich richtige Ausgang, denn eine namentliche Vorgabe
    ist genau das, was das Maß aus Abschnitt 3.6 als Ausnahme zählt.
    """
    if not forced_room:
        return rooms
    result: dict[str, list[Student]] = {name: [] for name in rooms}
    for name, people in rooms.items():
        for student in people:
            target = forced_room.get(student.matriculation_number, name)
            result.setdefault(target, []).append(student)
    return result


def _assign_rule_based(
    students: list[Student],
    venue: Venue,
    forced: list[ForcedAssignment],
    *,
    algorithm: str,
    weights: Weights,
    ga_config: GAConfig | None,
    rule_candidates: int,
    metrics: dict,
    seed: int = 1,
) -> tuple[SeatingPlan, dict[str, Rule]]:
    """Zweistufige Zuweisung: erst regelbeschreibbar auf Räume, dann auf Sitzplätze.

    Zurückgegeben wird neben dem Sitzplan die Einteilung je Raum, die
    aushängt. An ihr misst der Aushang seine beiden Listen der Abweichungen.

    Ausgewertet werden ``rule_candidates`` Regelstrukturen. Eine vollständige
    Auswertung aller Strukturen wäre zwar möglich, kostet aber ein Vielfaches an
    Rechenzeit, ohne das Ergebnis nennenswert zu verbessern.

    Die Vorauswahl zieht abwechselnd aus zwei Ordnungen: nach gleichmäßiger
    Raumauslastung und nach Regellänge. Keines der beiden Kriterien bestimmt die
    Vorauswahl damit allein. Ausgewählt wird am Ende die Struktur, die die
    meisten Prüflinge unterbringt, bei Gleichstand die mit weniger Ausnahmen
    und danach die mit der kürzeren Regel. Ausnahmen entstehen hier nur durch
    Platz- und Raumvorgaben, die der Einteilung widersprechen. Ohne solche
    Vorgaben sind alle Strukturen ausnahmefrei, und das mittlere Kriterium
    entscheidet nichts.
    """
    room_capacities = {name: len(venue.assignable_in(name)) for name in venue.rooms}
    all_groups = {s.seminar_group for s in students}
    rng = random.Random(seed)
    generated = list(candidate_room_plans(students, room_capacities, rng))
    if not generated:
        raise ValueError(
            "Es wurde keine regelbeschreibbare Raumzuordnung gefunden. Die "
            "Seminargruppen lassen sich nicht so auf die Räume verteilen, dass "
            "die Kapazitäten eingehalten werden."
        )

    def utilisation(p) -> float:
        return max(len(v) / room_capacities[r] for r, v in p.rooms.items())

    def rule_length_of(p) -> int:
        return plan_rule_length(p, all_groups)

    candidates = _alternate(
        sorted(generated, key=utilisation),
        sorted(generated, key=lambda p: (rule_length_of(p), utilisation(p))),
        rule_candidates,
    )

    forced_room = {f.matriculation_number: f.room for f in forced}
    forced_room.update(
        {s.matriculation_number: s.required_room for s in students if s.required_room}
    )

    best_candidate: SeatingPlan | None = None
    best_rules: dict[str, Rule] = {}
    best_quality: tuple[int, int, int] | None = None
    for room_plan in candidates:
        total = SeatingPlan()
        for current_room, people in _respect_forced_rooms(room_plan.rooms, forced_room).items():
            if not people:
                continue
            sub = subvenue(venue, {current_room}, include=True)
            room_forced = [f for f in forced if f.room == current_room]
            part, _ = _constructive_or_ga(
                people, sub, room_forced,
                algorithm=algorithm, weights=weights, ga_config=ga_config,
            )
            total.assignments.update(part.assignments)
            total.unassigned.extend(part.unassigned)
        exceptions = explainability_cost(total, venue, students) if forced_room else 0
        quality = (len(total.assignments), -exceptions, -rule_length_of(room_plan))
        if best_quality is None or quality > best_quality:
            best_candidate, best_quality = total, quality
            best_rules = dict(room_plan.rules)
            metrics["regeln"] = {
                current_room: render_rule(rule, all_groups)
                for current_room, rule in room_plan.rules.items()
            }
            metrics["regellaenge"] = rule_length_of(room_plan)

    assert best_candidate is not None
    metrics["gepruefte_einteilungsstrukturen"] = len(candidates)
    return best_candidate, best_rules


def _merge(plans: list[SeatingPlan]) -> SeatingPlan:
    merged = SeatingPlan()
    for plan in plans:
        merged.assignments.update(plan.assignments)
        merged.unassigned.extend(plan.unassigned)
    return merged


def assign(
    students: list[Student],
    venue: Venue,
    forced: list[ForcedAssignment] | None = None,
    *,
    algorithm: str = "greedy",
    weights: Weights | None = None,
    ga_config: GAConfig | None = None,
    nta_room_override: str | None = None,
    code_length: int | None = None,
    room_assignment: str = "free",
    rule_candidates: int = 24,
    max_exceptions: int | None = None,
    rule_seed: int = 1,
) -> AssignmentResult:
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unbekannter Algorithmus: '{algorithm}'.")
    if room_assignment not in ("free", "rules", "rules-soft"):
        raise ValueError(f"Unbekannte Raumzuordnung: '{room_assignment}'.")

    weights = weights or Weights()
    forced = list(forced or [])

    if code_length is None:
        code_length = minimal_code_length(students, len(venue.rooms))
        if code_length is None:
            best = max(DEFAULT_CODE_LENGTHS)
            highest_multiplicity = max(code_multiplicities(students, best).values(), default=0)
            raise ValueError(
                f"Mit bis zu {best} Endziffern lässt sich kein eindeutiger Aushangplan "
                f"erstellen: Ein Code wird {highest_multiplicity}-mal vergeben, es stehen aber nur "
                f"{len(venue.rooms)} Räume zur Trennung bereit. Mehr Stellen über "
                "--code-digits erzwingen oder zusätzliche Räume bereitstellen."
            )
    students = apply_code_length(students, code_length)

    nta_rooms = find_nta_rooms(venue, nta_room_override)
    nta_room_set = set(nta_rooms)
    students = resolve_room_requirements(students, venue, nta_rooms, forced)
    # Der feste Platz wird am Prüfling vermerkt. So erkennen Bewertung und
    # Bericht ein Paar, das F ausdrücklich nebeneinander setzt.
    students = with_fixed_seats(students, forced)
    nta_students, regular_students = split_by_nta_flag(students)

    plans: list[SeatingPlan] = []
    metrics: dict = {
        "nta_raeume": nta_rooms,
        "anzahl_nta_studierende": len(nta_students),
        "raumvorgaben": {
            s.matriculation_number: s.required_room for s in students if s.required_room
        },
        "vermerke_ohne_wirkung": ineffective_notes(students, forced),
    }

    if nta_students:
        if not nta_rooms:
            raise ValueError(
                f"{len(nta_students)} Studierende tragen den Vermerk '{NTA_FLAG}', "
                "es wurde aber kein NTA-Raum gefunden (Namenskonvention 'nta' "
                "oder Angabe über --nta-room)."
            )
        nta_venue = subvenue(venue, nta_room_set, include=True)
        nta_plan = greedy_assign(
            nta_students, nta_venue, [f for f in forced if f.room in nta_room_set]
        )
        plans.append(nta_plan)
        metrics["nta_zugewiesen"] = len(nta_plan.assignments)
        metrics["nta_nicht_zugewiesen"] = len(nta_plan.unassigned)

    regular_venue = subvenue(venue, nta_room_set, include=False)
    regular_forced = [f for f in forced if f.room not in nta_room_set]

    shown_rules: dict[str, Rule] | None = None
    if room_assignment == "free":
        regular_plan, figures = _constructive_or_ga(
            regular_students,
            regular_venue,
            regular_forced,
            algorithm=algorithm,
            weights=weights,
            ga_config=ga_config,
        )
        metrics.update(figures)
    else:
        regular_plan, shown_rules = _assign_rule_based(
            regular_students,
            regular_venue,
            regular_forced,
            algorithm=algorithm,
            weights=weights,
            ga_config=ga_config,
            rule_candidates=rule_candidates,
            metrics=metrics,
            seed=rule_seed,
        )
        if room_assignment == "rules-soft":
            regular_plan, history = fill_with_exceptions(
                regular_plan, regular_venue, regular_students, max_exceptions=max_exceptions
            )
            metrics["ausnahmen_verlauf"] = [list(pair) for pair in history]

    metrics["raumzuordnung"] = room_assignment
    metrics["ausnahmen"] = explainability_cost(
        regular_plan, regular_venue, regular_students
    )
    # Die blosse Zahl der Ausnahmen genuegt nicht: Ein Aushang, der eine
    # Einteilung nennt, ohne die Abweichungen aufzufuehren, ist irrefuehrend.
    # Beide Listen beziehen sich auf die Einteilung, die aushaengt. Das Mass
    # E(x) misst dagegen an der besten Einteilung je Raum und kann deshalb
    # kleiner sein als die Listen, etwa wenn eine Platzvorgabe einen
    # Pruefling aus dem Raum seiner Einteilung holt.
    metrics["ausnahmen_je_raum"] = room_exceptions(
        regular_plan, regular_venue, regular_students, shown=shown_rules
    )
    # Die Gegenrichtung: Wen die Einteilung eines Raumes nennt, der aber
    # anderswo sitzt. Ohne sie steht die betroffene Person vor der Tuer, die
    # ihr Anfangsbuchstabe ihr nennt, und findet dort keinen Hinweis.
    metrics["verweise_je_raum"] = room_redirects(
        regular_plan, regular_venue, regular_students, shown=shown_rules
    )
    if shown_rules:
        # Was tatsaechlich aushaengt: jede Ausnahme und jeder Verweis unter
        # einer ausgehaengten Einteilung. Die Zahl kann groesser sein als E(x).
        metrics["aushang_eintraege"] = sum(
            len(metrics["ausnahmen_je_raum"].get(room, []))
            + len(metrics["verweise_je_raum"].get(room, {}))
            for room in shown_rules
        )

    plans.append(regular_plan)
    metrics["anzeigecode_stellen"] = code_length

    return AssignmentResult(
        plan=_merge(plans),
        students=students,
        code_length=code_length,
        nta_rooms=nta_rooms,
        metrics=metrics,
        shown_rules=shown_rules or {},
    )
