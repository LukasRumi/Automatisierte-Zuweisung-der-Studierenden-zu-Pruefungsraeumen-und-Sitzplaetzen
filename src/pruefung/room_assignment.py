"""Erste Stufe der Zuweisung: die Verteilung der Studierenden auf die Räume.

Die Aufgabenstellung verlangt eine Raumzuordnung, die sich als Regel angeben
lässt (``A-K in GUxxx``, ``23MIB+25INB:A-D in FExxx``). Da jeder Raum genau
eine Regel mit genau einem Buchstabenbereich trägt, besitzt jede
ausnahmefrei regelbeschreibbare Zuordnung eine feste Struktur:

* Die Räume zerfallen in **Blöcke**. Einem Block ist eine Menge von
  Seminargruppen zugeordnet.
* Umfasst ein Block nur einen Raum, erhält dieser die Gruppen vollständig
  (Buchstabenbereich A-Z).
* Umfasst ein Block mehrere Räume, werden seine Studierenden alphabetisch auf
  diese aufgeteilt; jeder Raum erhält denselben Gruppensatz, aber einen eigenen,
  zusammenhängenden Buchstabenbereich.

Da die Bereiche eines Blocks lückenlos aneinander anschließen und die Blöcke
disjunkte Gruppenmengen besitzen, überdeckt jede Regel genau ihre eigenen
Prüflinge -- die Zuordnung ist damit ausnahmefrei im Sinne von
``pruefung.rules``. Diese Struktur spannt den Suchraum der harten Variante auf.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from itertools import chain, permutations, product

from pruefung.constraints import seat_conflicts
from pruefung.models import SeatingPlan, Student, Venue
from pruefung.rules import LETTERS, Rule, _initial, explainability_cost, rule_length


@dataclass(slots=True)
class RoomPlan:
    """Ergebnis der ersten Stufe: welcher Prüfling gehört in welchen Raum."""

    rooms: dict[str, list[Student]]
    rules: dict[str, Rule]

    def room_of(self, matriculation_number: str) -> str | None:
        for current_room, student_list in self.rooms.items():
            if any(s.matriculation_number == matriculation_number for s in student_list):
                return current_room
        return None


def _room_block_partitions(rooms: list[str]) -> list[list[list[str]]]:
    """Alle Zerlegungen der Räume in Blöcke (Mengenpartitionen).

    Die Räume sind wenige, sodass sich die Partitionen vollständig aufzählen
    lassen; bei drei regulären Räumen sind es fünf.
    """
    if not rooms:
        return [[]]
    first_room, rest = rooms[0], rooms[1:]
    partitions: list[list[list[str]]] = []
    for part in _room_block_partitions(rest):
        # Kopf in einen bestehenden Block aufnehmen ...
        for i in range(len(part)):
            extended = [list(block) for block in part]
            extended[i].insert(0, first_room)
            partitions.append(extended)
        # ... oder einen eigenen Block eröffnen.
        partitions.append([[first_room], *[list(block) for block in part]])
    return partitions


ORDER_LIMIT = 24
"""Höchstzahl der je Block geprüften Raumreihenfolgen."""


def _room_orders(
    rooms: list[str], rng: random.Random, limit: int = ORDER_LIMIT
) -> list[list[str]]:
    """Reihenfolgen, in denen die Räume eines Blocks Buchstabenbereiche erhalten.

    Bei wenigen Räumen werden alle Reihenfolgen geprüft, bei vielen eine
    Stichprobe, da deren Zahl mit der Fakultät wächst.
    """
    if len(rooms) <= 1:
        return [list(rooms)]
    covers_all = list(permutations(rooms))
    if len(covers_all) <= limit:
        return [list(order) for order in covers_all]
    chosen = [list(rooms)]
    for _ in range(limit - 1):
        shuffled_rooms = list(rooms)
        rng.shuffle(shuffled_rooms)
        chosen.append(shuffled_rooms)
    return chosen


def _ordered_room_blocks(rooms: list[str], rng: random.Random):
    """Zerlegungen der Räume in Blöcke, samt Reihenfolgen innerhalb der Blöcke.

    Innerhalb eines Blocks entscheidet die Reihenfolge, welcher Raum welchen
    Buchstabenbereich erhält. Da die Räume unterschiedlich groß sind und die
    Anfangsbuchstaben ungleich häufig vorkommen, ist nur ein Teil der
    Reihenfolgen mit den Kapazitäten vereinbar. Eine feste Reihenfolge
    übergeht daher ganze Familien zulässiger Zuordnungen, darunter gerade die
    kürzesten: Eine Einteilung, die allein aus Buchstabenbereichen besteht und
    keine Seminargruppe nennt, setzt einen einzigen Block über alle Räume
    voraus und ist genau dann erreichbar, wenn eine passende Reihenfolge
    geprüft wird.
    """
    for partition in _room_block_partitions(rooms):
        variants = [_room_orders(block, rng) for block in partition]
        for combination in product(*variants):
            yield [list(block) for block in combination]


def _split_alphabetically(
    student_list: list[Student], room_ids: list[str], room_capacities: dict[str, int]
) -> dict[str, Rule] | None:
    """Teilt einen Block alphabetisch auf seine Räume auf.

    Die Schnitte folgen den Kapazitäten: Jeder Raum erhält so viele
    Anfangsbuchstaben, wie er fassen kann. Ein Schnitt kann nur zwischen zwei
    Buchstaben liegen -- Prüflinge mit demselben Anfangsbuchstaben bleiben
    zusammen, da eine Regel sie nicht trennen könnte. Passt der Block dadurch
    nicht in die Räume, wird ``None`` zurückgegeben.
    """
    group_names = frozenset(s.seminar_group for s in student_list)
    per_letter: dict[str, int] = {letter: 0 for letter in LETTERS}
    without_names = 0
    for s in student_list:
        letter = _initial(s)
        if letter is None or letter not in per_letter:
            without_names += 1
        else:
            per_letter[letter] += 1

    if without_names and len(room_ids) > 1:
        # Ohne Namen ist keine alphabetische Aufteilung möglich.
        return None

    rule_by_room: dict[str, Rule] = {}
    index = 0
    for position, current_room in enumerate(room_ids):
        last = position == len(room_ids) - 1
        start = LETTERS[index] if index < len(LETTERS) else LETTERS[-1]
        occupied = 0
        while index < len(LETTERS):
            if not last and occupied + per_letter[LETTERS[index]] > room_capacities[current_room]:
                break
            occupied += per_letter[LETTERS[index]]
            index += 1
        end = LETTERS[index - 1] if index > 0 else LETTERS[0]
        if occupied > room_capacities[current_room]:
            return None
        rule_by_room[current_room] = Rule(group_names, start, end if index > 0 else start)
    # Der letzte Raum übernimmt den Rest des Alphabets.
    if rule_by_room:
        last_room = room_ids[-1]
        previous_rule = rule_by_room[last_room]
        rule_by_room[last_room] = Rule(previous_rule.groups, previous_rule.letter_from, LETTERS[-1])
    return rule_by_room


def build_room_plan(
    students: list[Student],
    capacities: dict[str, int],
    group_blocks: list[frozenset[str]],
    room_blocks: list[list[str]],
) -> RoomPlan | None:
    """Setzt eine Blockstruktur in eine konkrete, regelbeschreibbare Raumzuordnung um.

    Gibt ``None`` zurück, wenn die Struktur nicht zu den Kapazitäten passt.
    """
    if len(group_blocks) != len(room_blocks):
        return None

    rule_by_room: dict[str, Rule] = {}
    for group_names, room_ids in zip(group_blocks, room_blocks):
        members = [s for s in students if s.seminar_group in group_names]
        if len(room_ids) == 1:
            current_room = room_ids[0]
            if len(members) > capacities[current_room]:
                return None
            rule_by_room[current_room] = Rule(frozenset(group_names), LETTERS[0], LETTERS[-1])
        else:
            part = _split_alphabetically(members, room_ids, capacities)
            if part is None:
                return None
            rule_by_room.update(part)

    occupancy: dict[str, list[Student]] = {current_room: [] for current_room in capacities}
    for student in students:
        matching = [current_room for current_room, rule in rule_by_room.items() if rule.covers(student)]
        if len(matching) != 1:
            # Keine oder mehrdeutige Zuordnung: die Struktur ist nicht gültig.
            return None
        occupancy[matching[0]].append(student)

    if any(len(v) > capacities[current_room] for current_room, v in occupancy.items()):
        return None
    return RoomPlan(rooms=occupancy, rules=rule_by_room)


def _distribute(names: list[str], block_count: int, rng: random.Random) -> list[int] | None:
    """Ordnet jedem Namen zufällig einen Block zu, wobei kein Block leer bleibt."""
    if block_count > len(names):
        return None
    assignment = list(range(block_count)) + [
        rng.randrange(block_count) for _ in range(len(names) - block_count)
    ]
    rng.shuffle(assignment)
    return assignment


def random_group_blocks(
    groups: list[str], block_count: int, rng: random.Random
) -> list[frozenset[str]] | None:
    """Verteilt die Seminargruppen einzeln auf die gewünschte Zahl von Blöcken."""
    assignment = _distribute(groups, block_count, rng)
    if assignment is None:
        return None
    blocks: list[set[str]] = [set() for _ in range(block_count)]
    for group, target in zip(groups, assignment):
        blocks[target].add(group)
    return [frozenset(b) for b in blocks]


def group_prefixes(groups: list[str]) -> dict[str, set[str]]:
    """Fasst Seminargruppen nach ihrem gemeinsamen Präfix zusammen.

    Aus ``25INB-1``, ``25INB-2`` und ``25INB-3`` wird der Präfix ``25INB``,
    der Jahrgang und Studiengang bezeichnet.
    """
    by_prefix: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        by_prefix[group.split("-", 1)[0]].add(group)
    return dict(by_prefix)


def prefix_group_blocks(
    groups: list[str], block_count: int, rng: random.Random
) -> list[frozenset[str]] | None:
    """Verteilt ganze Präfixe statt einzelner Seminargruppen auf die Blöcke.

    Bleiben Geschwistergruppen zusammen, lassen sie sich in der Regel zu ihrem
    Präfix zusammenfassen (aus ``25INB-1+25INB-2+25INB-3`` wird ``25INB``). Die
    Regeln werden dadurch erheblich kürzer, ohne dass Kapazität verloren geht.
    """
    by_prefix = group_prefixes(groups)
    names = sorted(by_prefix)
    assignment = _distribute(names, block_count, rng)
    if assignment is None:
        return None
    blocks: list[set[str]] = [set() for _ in range(block_count)]
    for name, target in zip(names, assignment):
        blocks[target].update(by_prefix[name])
    return [frozenset(b) for b in blocks]


def candidate_room_plans(
    students: list[Student],
    capacities: dict[str, int],
    rng: random.Random,
    attempts: int = 200,
):
    """Erzeugt regelbeschreibbare Raumzuordnungen als Kandidaten für die Suche.

    Erzeugt werden zuerst Zuordnungen, die ganze Präfixe zusammenhalten und
    damit kurze Regeln ermöglichen, anschließend solche, die die Seminargruppen
    einzeln verteilen. Letztere bleiben erforderlich, da sich die Kapazitäten
    nicht auf jeder Instanz mit ganzen Präfixen einhalten lassen.

    Die Blockstrukturen umfassen auch die Reihenfolgen der Räume innerhalb
    eines Blocks, siehe ``_ordered_room_blocks``.

    Zurückgegeben wird jede Zuordnung nur einmal. Verschiedene Blockstrukturen
    führen regelmäßig auf dieselben Regeln, etwa wenn die Gruppenaufteilung für
    die Regeln ohne Belang ist. Ohne diese Entdoppelung füllten solche
    Wiederholungen das Kandidatenbudget der Suche, ohne eine neue Möglichkeit
    beizutragen.
    """
    group_names = sorted({s.seminar_group for s in students})
    room_ids = sorted(capacities)
    seen: set[frozenset[tuple[str, Rule]]] = set()
    for block_function in (prefix_group_blocks, random_group_blocks):
        for room_blocks in _ordered_room_blocks(room_ids, rng):
            for _ in range(attempts):
                group_blocks = block_function(group_names, len(room_blocks), rng)
                if group_blocks is None:
                    continue
                plan = build_room_plan(students, capacities, group_blocks, room_blocks)
                if plan is None:
                    continue
                identifier = frozenset(plan.rules.items())
                if identifier in seen:
                    continue
                seen.add(identifier)
                yield plan


def plan_rule_length(plan: RoomPlan, all_groups: set[str]) -> int:
    """Länge der längsten Regel eines Raumplans, gemessen in Bezeichnern."""
    return max(
        (rule_length(rule, all_groups) for rule in plan.rules.values()), default=0
    )


def fill_with_exceptions(
    plan: SeatingPlan,
    venue: Venue,
    students: list[Student],
    nta_rooms: list[str] | None = None,
    max_exceptions: int | None = None,
) -> tuple[SeatingPlan, list[tuple[int, int]]]:
    """Weicht die Regelbindung schrittweise auf und protokolliert die Abwägung.

    Ausgangspunkt ist ein regelbeschreibbarer, aber unvollständiger Sitzplan.
    Nacheinander werden unversorgte Prüflinge auf freie, konfliktfreie Plätze
    gesetzt -- auch in Räumen, die ihre Regel nicht vorsieht. Jede solche
    Platzierung ist eine Ausnahme im Sinne von ``pruefung.rules``, wie sie in
    der Praxis als namentlicher Zusatz unter der Regel stünde.

    Gewählt wird in jedem Schritt die Platzierung mit dem geringsten Zuwachs an
    Ausnahmen. ``max_exceptions`` begrenzt, wie viele Ausnahmen dabei entstehen
    dürfen; ohne Angabe wird gefüllt, solange überhaupt Platzierungen möglich
    sind.

    Zurückgegeben werden der erweiterte Sitzplan und die Folge der Zustände als
    Paare ``(Ausnahmen, platzierte Prüflinge)``. Letztere bildet die
    Abwägungskurve zwischen Erklärbarkeit und Kapazitätsausnutzung.
    """
    by_id = {s.matriculation_number: s for s in students}
    plan = plan.copy()
    history = [
        (
            explainability_cost(plan, venue, students, nta_rooms),
            len(plan.assignments),
        )
    ]

    pending = list(plan.unassigned)
    while pending:
        best_candidate: tuple[int, str, str] | None = None  # (Kosten, Matrikelnummer, Sitzplatz)
        for matriculation_number in pending:
            student = by_id[matriculation_number]
            for current_room in venue.rooms:
                if current_room in set(nta_rooms or []):
                    continue
                # Je Raum genügt ein freier, konfliktfreier Platz als Kandidat:
                # welcher es ist, ändert die Ausnahmezahl nicht.
                candidate = next(
                    (
                        seat_id
                        for seat_id in venue.assignable_in(current_room)
                        if seat_id not in plan.assignments
                        and not seat_conflicts(seat_id, student, plan, by_id, venue)
                    ),
                    None,
                )
                if candidate is None:
                    continue
                plan.assignments[candidate] = matriculation_number
                costs = explainability_cost(plan, venue, students, nta_rooms)
                del plan.assignments[candidate]
                if best_candidate is None or costs < best_candidate[0]:
                    best_candidate = (costs, matriculation_number, candidate)
        if best_candidate is None:
            break
        costs, matriculation_number, seat_id = best_candidate
        if max_exceptions is not None and costs > max_exceptions:
            break
        plan.assignments[seat_id] = matriculation_number
        plan.unassigned.remove(matriculation_number)
        pending.remove(matriculation_number)
        history.append((costs, len(plan.assignments)))

    return plan, history


def all_rules(plan: RoomPlan) -> list[tuple[str, Rule]]:
    return sorted(plan.rules.items())


def covered_students(plan: RoomPlan) -> list[Student]:
    return list(chain.from_iterable(plan.rooms.values()))
