"""Regelbasierte Beschreibung der Raumzuordnung und ihr Erklärbarkeitsmaß.

Die Aufgabenstellung verlangt eine \"möglichst klare Zuordnung der Studierenden
auf die Räume\" und nennt dafür Beispiele wie ``A-K in GUxxx``,
``MIB1 in GUxxx`` oder ``23MIB+25INB:A-D in FExxx``. Allen gemeinsam ist die
Form

    {Seminargruppen} x {Namensbereich} -> Raum

Eine solche Regel ist hier als ``Rule`` abgebildet: eine Menge von
Seminargruppen und ein zusammenhängender Bereich von Anfangsbuchstaben des
Nachnamens. Ein zusammenhängender Bereich ist Bedingung -- ``A-K`` ist als
Aushang lesbar, ``A, C, F-H, Z`` nicht.

**Erklärbarkeitsmaß.** Wie gut eine gegebene Zuordnung durch Regeln
beschreibbar ist, misst die Zahl der *Ausnahmen*. Sie ist zweiseitig zu
verstehen, denn eine Regel ist eine Aussage über alle Studierenden:

* Prüflinge im Raum, die seine Regel nicht abdeckt (die Regel ist unvollständig).
* Prüflinge außerhalb, die seine Regel abdeckt (die Regel ist zu weit gefasst).

Ohne den zweiten Teil wäre das Maß wertlos, da die Regel \"alle Gruppen, A-Z\"
jeden Raum vollständig abdeckte. Formal ist die Ausnahmezahl eines Raumes die
Mächtigkeit der symmetrischen Differenz zwischen seiner Belegung und der von
der Regel abgedeckten Menge, minimiert über alle Regeln.
"""

from __future__ import annotations

import string
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from pruefung.models import SeatingPlan, Student, Venue, normalise_letter

LETTERS = string.ascii_uppercase


@dataclass(frozen=True, slots=True)
class Rule:
    """Eine Zuordnungsregel: Seminargruppen und ein Bereich von Anfangsbuchstaben."""

    groups: frozenset[str]
    letter_from: str
    letter_to: str

    def covers(self, student: Student) -> bool:
        if student.seminar_group not in self.groups:
            return False
        letter = _initial(student)
        if letter is None:
            # Ohne Namen ist keine alphabetische Einordnung möglich; die
            # Buchstabenbedingung gilt dann als erfüllt, damit solche Prüflinge
            # das Maß nicht künstlich verschlechtern.
            return True
        return self.letter_from <= letter <= self.letter_to

    def covers_all_letters(self) -> bool:
        return self.letter_from == LETTERS[0] and self.letter_to == LETTERS[-1]


def _initial(student: Student) -> str | None:
    """Anfangsbuchstabe des Nachnamens als Buchstabe von A bis Z.

    Gibt ``None`` zurück, wenn kein Name vorliegt oder der erste Buchstabe sich
    keinem Buchstaben zuordnen lässt. Umlaute werden über
    ``normalise_letter`` auf ihren Grundbuchstaben abgebildet.
    """
    last_name = student.last_name
    return normalise_letter(last_name[0]) if last_name else None


def best_rule_for_room(
    occupants: list[Student], all_students: list[Student]
) -> tuple[Rule, int]:
    """Bestimmt die Regel mit den wenigsten Ausnahmen für eine Raumbelegung.

    Für einen festen Buchstabenbereich zerfällt die Entscheidung über die
    Gruppenmenge in unabhängige Einzelentscheidungen: Eine Gruppe aufzunehmen
    kostet so viele Ausnahmen, wie Mitglieder außerhalb des Raumes im Bereich
    liegen; sie wegzulassen kostet so viele, wie Mitglieder im Raum darin
    liegen. Es genügt daher, je Gruppe das Minimum zu wählen. Das exakte
    Optimum ist damit ohne Suche über Gruppenteilmengen bestimmbar.
    """
    in_room = {s.matriculation_number for s in occupants}

    inside: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    outside: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # Prüflinge ohne Namen gelten für jeden Buchstabenbereich als enthalten.
    inside_unnamed: dict[str, int] = defaultdict(int)
    outside_unnamed: dict[str, int] = defaultdict(int)

    for student in all_students:
        inside_count = student.matriculation_number in in_room
        letter = _initial(student)
        if letter is None:
            (inside_unnamed if inside_count else outside_unnamed)[student.seminar_group] += 1
        else:
            (inside if inside_count else outside)[student.seminar_group][letter] += 1

    group_names = sorted(
        set(inside) | set(outside) | set(inside_unnamed) | set(outside_unnamed)
    )

    # Präfixsummen über die Buchstaben: Damit kostet die Auswertung eines
    # Bereichs je Gruppe nur noch eine Subtraktion statt einer Schleife über
    # alle 26 Buchstaben.
    def _prefix(counter: dict[str, int]) -> list[int]:
        totals = [0]
        for letter in LETTERS:
            totals.append(totals[-1] + counter.get(letter, 0))
        return totals

    inside_prefix = {g: _prefix(inside[g]) for g in group_names}
    outside_prefix = {g: _prefix(outside[g]) for g in group_names}
    inside_total = {g: inside_prefix[g][-1] for g in group_names}

    best_rule: Rule | None = None
    best_costs = -1

    for i, lo in enumerate(LETTERS):
        for j in range(i, len(LETTERS)):
            hi = LETTERS[j]
            chosen: set[str] = set()
            costs = 0
            for group in group_names:
                in_range = inside_prefix[group][j + 1] - inside_prefix[group][i]
                inside_count = inside_unnamed[group] + in_range
                outside_count = (
                    outside_unnamed[group]
                    + outside_prefix[group][j + 1]
                    - outside_prefix[group][i]
                )
                if outside_count < inside_count:
                    chosen.add(group)
                    costs += outside_count
                else:
                    costs += inside_count
                # Prüflinge im Raum außerhalb des Bereichs bleiben stets Ausnahmen.
                costs += inside_total[group] - in_range
            if best_costs < 0 or costs < best_costs:
                best_costs = costs
                best_rule = Rule(frozenset(chosen), lo, hi)

    assert best_rule is not None
    return best_rule, best_costs


def explainability_cost(
    plan: SeatingPlan,
    venue: Venue,
    students: list[Student],
    nta_rooms: list[str] | None = None,
) -> int:
    """Gesamtzahl der Ausnahmen über alle Räume; 0 bedeutet vollständig regelbeschreibbar."""
    return sum(cost for _, cost in room_rules(plan, venue, students, nta_rooms).values())


def room_rules(
    plan: SeatingPlan,
    venue: Venue,
    students: list[Student],
    nta_rooms: list[str] | None = None,
) -> dict[str, tuple[Rule | None, int]]:
    """Bestimmt je belegtem Raum die beste Regel samt zugehöriger Ausnahmezahl.

    Räume für Nachteilsausgleiche bleiben ausgenommen: Ihre Belegung folgt
    bereits einer eigenen, klar formulierbaren Regel (\"alle Prüflinge mit
    Nachteilsausgleich\") und ist über Seminargruppen und Anfangsbuchstaben
    grundsätzlich nicht beschreibbar. Sie erhalten daher ``None`` als Regel und
    null Ausnahmen, damit das Maß nicht systematisch verzerrt wird.

    Bewertet werden ausschließlich platzierte Prüflinge. Andernfalls zählte ein
    unversorgter Prüfling als \"von der Regel abgedeckt, aber nicht im Raum\"
    und damit als Ausnahme -- die Zahl der Ausnahmen wäre dann an die Zahl der
    Unversorgten gekoppelt, und beide Größen ließen sich nicht mehr
    gegeneinander abwägen.
    """
    nta = set(nta_rooms or [])
    placed = set(plan.assignments.values())
    students = [s for s in students if s.matriculation_number in placed]
    by_id = {s.matriculation_number: s for s in students}

    occupancy: dict[str, list[Student]] = {name: [] for name in venue.rooms}
    for seat_id, matriculation_number in plan.assignments.items():
        occupancy[venue.seats[seat_id].room].append(by_id[matriculation_number])

    # Prüflinge des NTA-Raumes zählen auch außerhalb nicht mit: Sie stehen für
    # die regulären Räume gar nicht zur Verfügung.
    in_nta_room = {
        s.matriculation_number for current_room in nta for s in occupancy.get(current_room, [])
    }
    regular_students = [
        s for s in students if s.matriculation_number not in in_nta_room
    ]

    result: dict[str, tuple[Rule | None, int]] = {}
    for current_room, occupants in occupancy.items():
        if not occupants:
            continue
        if current_room in nta:
            result[current_room] = (None, 0)
        else:
            result[current_room] = best_rule_for_room(occupants, regular_students)
    return result


def _placed_by_room(
    plan: SeatingPlan,
    venue: Venue,
    students: list[Student],
    nta_rooms: list[str] | None,
) -> tuple[dict[str, list[Student]], dict[str, str], list[Student]]:
    """Belegung je Raum, Sitzraum je Prüfling und die platzierten regulären Prüflinge."""
    nta = set(nta_rooms or [])
    placed = set(plan.assignments.values())
    present = [s for s in students if s.matriculation_number in placed]
    by_id = {s.matriculation_number: s for s in present}

    occupancy: dict[str, list[Student]] = {name: [] for name in venue.rooms}
    room_of: dict[str, str] = {}
    for seat_id, matriculation_number in plan.assignments.items():
        current = venue.seats[seat_id].room
        occupancy[current].append(by_id[matriculation_number])
        room_of[matriculation_number] = current

    # Prüflinge des NTA-Raumes zählen auch außerhalb nicht mit: Sie stehen für
    # die regulären Räume gar nicht zur Verfügung.
    in_nta = {s.matriculation_number for name in nta for s in occupancy.get(name, [])}
    regular = [s for s in present if s.matriculation_number not in in_nta]
    return occupancy, room_of, regular


def _listed_rules(
    occupancy: dict[str, list[Student]],
    regular: list[Student],
    nta_rooms: list[str] | None,
    shown: Mapping[str, Rule] | None,
) -> dict[str, Rule]:
    """Die Einteilung je Raum, an der beide Listen des Aushangs gemessen werden.

    Hängt eine Einteilung aus, gilt sie, und zwar auch für einen Raum, in dem
    niemand sitzt. Nur so stimmen die Listen mit dem überein, was am Aushang
    steht. Die beste Regel je Raum, die ``explainability_cost`` zugrunde legt,
    kann davon abweichen. Weil die ausgehängte Einteilung jeden Prüfling genau
    einem Raum zuweist, erscheint dann jede Abweichung genau zweimal: als
    Ausnahme im Sitzraum und als Verweis im Raum der Einteilung.

    Ohne ausgehängte Einteilung, also bei freier Zuordnung, dient je
    belegtem Raum die beste Regel.
    """
    nta = set(nta_rooms or [])
    rules: dict[str, Rule] = {}
    for name, occupants in occupancy.items():
        if name in nta:
            continue
        if shown is not None and name in shown:
            rules[name] = shown[name]
        elif occupants:
            rules[name], _ = best_rule_for_room(occupants, regular)
    return rules


def room_exceptions(
    plan: SeatingPlan,
    venue: Venue,
    students: list[Student],
    nta_rooms: list[str] | None = None,
    shown: Mapping[str, Rule] | None = None,
) -> dict[str, list[str]]:
    """Benennt je Raum die Prüflinge, die von seiner Einteilung abweichen.

    Das Maß aus ``explainability_cost`` liefert nur deren Anzahl. Für den
    Aushang und den Auswertungsreport wird jedoch gebraucht, \\emph{wer} es
    ist, denn eine Einteilung mit Ausnahmen ist ohne die Namensliste
    unvollständig und damit irreführend.

    Gezählt wird nur die erste Richtung, also wer im Raum sitzt, ohne von
    dessen Einteilung erfasst zu sein. Die zweite Richtung, von der Einteilung
    erfasst und anderswo platziert, erscheint beim jeweils anderen Raum.
    ``shown`` ist die ausgehängte Einteilung je Raum (siehe ``_listed_rules``).
    """
    occupancy, _, regular = _placed_by_room(plan, venue, students, nta_rooms)
    return {
        name: sorted(s.matriculation_number for s in occupancy[name] if not rule.covers(s))
        for name, rule in _listed_rules(occupancy, regular, nta_rooms, shown).items()
    }


def room_redirects(
    plan: SeatingPlan,
    venue: Venue,
    students: list[Student],
    nta_rooms: list[str] | None = None,
    shown: Mapping[str, Rule] | None = None,
) -> dict[str, dict[str, str]]:
    """Benennt je Raum, wen seine Einteilung erfasst, der aber anderswo sitzt.

    ``room_exceptions`` liefert die erste Richtung der symmetrischen Differenz,
    also wer im Raum sitzt, ohne von dessen Einteilung erfasst zu sein. Diese
    Funktion liefert die zweite.

    Für den Aushang ist gerade die zweite Richtung die wichtigere. Wer vor einer
    Tür steht, hat den Raum nach seinem Anfangsbuchstaben ausgewählt. Findet er
    sich auf der Karte nicht wieder, bleibt ihm ohne einen Hinweis nur, die
    übrigen Räume abzulaufen. Erst der Verweis macht aus einer Suche einen
    einzigen weiteren Weg.

    Zurückgegeben wird je Raum eine Zuordnung von der Matrikelnummer auf den
    Raum, in dem der Prüfling tatsächlich sitzt. Die Regel je Raum wird dabei
    genauso bestimmt wie in ``room_exceptions``, sodass beide Richtungen
    dieselbe Einteilung beschreiben.
    """
    occupancy, room_of, regular = _placed_by_room(plan, venue, students, nta_rooms)
    return {
        name: {
            s.matriculation_number: room_of[s.matriculation_number]
            for s in regular
            if rule.covers(s) and room_of[s.matriculation_number] != name
        }
        for name, rule in _listed_rules(occupancy, regular, nta_rooms, shown).items()
    }


def _collapse_groups(groups: frozenset[str], all_groups: set[str]) -> list[str]:
    """Fasst Seminargruppen zu Präfixen zusammen, sofern alle Geschwister enthalten sind.

    Aus ``{25INB-1, 25INB-2, 25INB-3}`` wird so ``25INB`` -- die Schreibweise,
    die auch in der Aufgabenstellung verwendet wird.
    """
    by_prefix: dict[str, set[str]] = defaultdict(set)
    for group in all_groups:
        by_prefix[group.split("-", 1)[0]].add(group)

    parts: list[str] = []
    rest = set(groups)
    for prefix, siblings in sorted(by_prefix.items()):
        if len(siblings) > 1 and siblings <= groups:
            parts.append(prefix)
            rest -= siblings
    parts.extend(sorted(rest))
    return sorted(parts)


def rule_length(rule: Rule, all_groups: set[str]) -> int:
    """Zahl der Bezeichner, die eine Regel aufzählen muss.

    Das ist die zweite Gütedimension neben der Ausnahmezahl. Eine Regel kann
    ausnahmefrei und trotzdem unbrauchbar sein, wenn sie dreizehn
    Seminargruppen einzeln benennt. Gezählt wird, was in der aushängbaren
    Schreibweise mit ``+`` verbunden erscheint; deckt die Regel alle Gruppen
    ab, nennt sie keine und die Länge ist 0.
    """
    if not rule.groups or rule.groups >= all_groups:
        return 0
    return len(_collapse_groups(rule.groups, all_groups))


def render_rule(rule: Rule, all_groups: set[str]) -> str:
    """Formuliert eine Regel so, wie sie am Aushang stehen könnte.

    Entartete Komponenten werden weggelassen, da sie keine Information tragen:
    Deckt die Regel alle Seminargruppen ab, bleibt nur der Namensbereich übrig
    (``A-K``), deckt sie alle Buchstaben ab, nur die Gruppen (``23MIB+25INB``).
    Beides entspricht den Beispielen der Aufgabenstellung.
    """
    if not rule.groups:
        return "(keine Gruppe)"
    all_letters = rule.covers_all_letters()
    covers_all = rule.groups >= all_groups
    if covers_all and all_letters:
        return "alle"

    if rule.letter_from == rule.letter_to:
        letter_range = rule.letter_from
    else:
        letter_range = f"{rule.letter_from}-{rule.letter_to}"

    if covers_all:
        return letter_range
    group_names = "+".join(_collapse_groups(rule.groups, all_groups))
    if all_letters:
        return group_names
    return f"{group_names}: {letter_range}"
