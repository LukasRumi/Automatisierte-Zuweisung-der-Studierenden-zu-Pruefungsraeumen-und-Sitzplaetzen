"""Nachbarschaftsberechnung, harte Restriktionen und die weiche Zielfunktion Z.

Die hier implementierten Funktionen setzen die in Kapitel 3 der Arbeit
formal beschriebene Modellierung um:

* ``compute_neighbors``      berechnet N_p für jeden Sitzplatz p.
* ``seat_conflicts_with_group`` / ``find_hard_violations``
  prüfen die Trennung von Seminargruppen (harte Restriktion). Zwei Prüflinge,
  die beide auf ihrem festen Platz aus F sitzen, sind davon ausgenommen
  (``with_fixed_seats``, ``find_forced_neighbor_pairs``).
* ``room_admits`` / ``find_room_requirement_violations``
  prüfen die Raumvorgaben, also den eingeengten Wertebereich D(s).
* ``fragmentation_cost``, ``sorting_cost``, ``compactness_gap_cost``
  entsprechen den Kostenfunktionen C1, C2 und C3.
* ``Weights`` / ``objective`` bilden die gewichtete Zielfunktion
  Z = sum_i w_i * C_i(x) ab.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from pruefung.models import (
    ForcedAssignment,
    SeatingPlan,
    Seat,
    Student,
    Venue,
    normalise_letter,
    replace_student,
)

DEFAULT_NEIGHBOR_RADIUS = 2.65
"""Radius der Nachbarschaft in Sitzbreiten (eine Sitzbreite = 1.0).

In realen Prüfungsbestuhlungen bleibt typischerweise jeder zweite Sitz frei
(Muster ``X.X.X.X``). Die dort tatsächlich auftretenden Abstände zwischen
zuweisbaren Plätzen bilden keine kontinuierliche Skala, sondern einzelne
Werte: 1.00 (Platz davor bzw. dahinter), 2.00 (seitlicher Nachbar sowie Platz
hinter einer freien Reihe), 2.06 und 2.50 (halb versetzte Reihen, vgl. das
Zeichen ``<``), 2.24 (diagonal), 2.83 (diagonal über eine freie Reihe),
danach 3.00 und mehr.

Der Standardwert erfasst die unmittelbare Umgebung bis einschließlich der
Diagonalen und der versetzten Reihen. Er liegt mittig zwischen 2.50 und 2.83,
also in der größten Lücke unter denjenigen Schwellen, die überhaupt in Frage
kommen. Kleinere Schwellen ließen den seitlichen Nachbarn zu, was die
Restriktion ihres Zwecks berauben würde. Die Lage mittig in der Lücke sorgt
dafür, dass die Schwelle nicht unmittelbar auf einem real auftretenden Abstand
liegt: Andernfalls könnten geringfügig abweichende Bestuhlungen die
Nachbarschaft unbeabsichtigt umschlagen lassen.
Über ``--neighbor-radius`` ist der Wert je Prüfung anpassbar."""


def compute_neighbors(
    seats: dict[str, Seat], radius: float = DEFAULT_NEIGHBOR_RADIUS
) -> dict[str, frozenset[str]]:
    """Berechnet N_p für jeden Sitzplatz auf Basis der euklidischen Distanz.

    Die Nachbarschaft wird ausschließlich innerhalb desselben Raumes gebildet,
    da räumlich getrennte Prüfungsräume keine Täuschungsgefahr durch Nähe bergen.
    """
    neighbors: dict[str, set[str]] = {seat_id: set() for seat_id in seats}

    by_room: dict[str, list[Seat]] = defaultdict(list)
    for seat in seats.values():
        by_room[seat.room].append(seat)

    for room_seats in by_room.values():
        for a, b in combinations(room_seats, 2):
            distance = math.hypot(a.x - b.x, a.y - b.y)
            if distance <= radius:
                neighbors[a.id].add(b.id)
                neighbors[b.id].add(a.id)

    return {seat_id: frozenset(ids) for seat_id, ids in neighbors.items()}


def seat_conflicts_with_group(
    seat_id: str,
    seminar_group: str,
    plan: SeatingPlan,
    students_by_id: dict[str, Student],
    neighbors: dict[str, frozenset[str]],
) -> bool:
    """Prüft, ob das Setzen eines Studierenden der gegebenen Gruppe auf ``seat_id``
    die harte Trennungs-Restriktion verletzen würde."""
    for neighbor_id in neighbors.get(seat_id, ()):
        occupant = plan.assignments.get(neighbor_id)
        if occupant is not None and students_by_id[occupant].seminar_group == seminar_group:
            return True
    return False


def seat_conflicts_with_code(
    seat_id: str,
    display_code: str,
    plan: SeatingPlan,
    students_by_id: dict[str, Student],
    venue: Venue,
) -> bool:
    """Prüft, ob der Anzeigecode im Raum des Platzes bereits vergeben ist.

    Da je Raum ein eigener Aushangplan entsteht, muss der Code nur innerhalb
    eines Raumes eindeutig sein. Ein leerer Code bedeutet, dass für diesen
    Studierenden keine Endziffern veröffentlicht werden; die Restriktion
    greift dann nicht.

    Der Platz selbst bleibt außer Betracht. Die konstruktiven Verfahren fragen
    nur freie Plätze ab, die Reparatur des Genetischen Algorithmus aber prüft
    einen Tausch, nachdem sie ihn ausgeführt hat. Ohne diese Ausnahme fände sie
    dabei den Code des eingetauschten Prüflings selbst und verwürfe jeden Tausch.
    """
    if not display_code:
        return False
    room = venue.seats[seat_id].room
    for other_seat, matriculation_number in plan.assignments.items():
        if other_seat == seat_id or venue.seats[other_seat].room != room:
            continue
        if students_by_id[matriculation_number].display_code == display_code:
            return True
    return False


def room_admits(student: Student, room_name: str) -> bool:
    """Prüft, ob ein Raum im Wertebereich D(s) des Prüflings liegt.

    Eingeengt wird der Wertebereich hier nur durch eine Raumvorgabe. Die
    Raumbindung der Nachteilsausgleiche wirkt bereits über die Zerlegung in
    zwei Teilprobleme (siehe ``pruefung.pipeline``) und muss daher nicht je
    Platz geprüft werden.
    """
    return not student.required_room or student.required_room == room_name


def seat_conflicts(
    seat_id: str,
    student: Student,
    plan: SeatingPlan,
    students_by_id: dict[str, Student],
    venue: Venue,
) -> bool:
    """Prüft alle platzierungsbezogenen harten Restriktionen auf einmal.

    Das sind die Raumvorgabe, die Trennung der Seminargruppen und die
    Eindeutigkeit des Anzeigecodes. Die Raumvorgabe steht vorn, da sie am
    wenigsten kostet.
    """
    return (
        not room_admits(student, venue.seats[seat_id].room)
        or seat_conflicts_with_group(
            seat_id, student.seminar_group, plan, students_by_id, venue.neighbors
        )
        or seat_conflicts_with_code(seat_id, student.display_code, plan, students_by_id, venue)
    )


def find_room_requirement_violations(
    plan: SeatingPlan, venue: Venue, students_by_id: dict[str, Student]
) -> list[str]:
    """Findet Sitzplätze, deren Prüfling außerhalb seines vorgegebenen Raumes sitzt."""
    return sorted(
        seat_id
        for seat_id, matriculation_number in plan.assignments.items()
        if not room_admits(students_by_id[matriculation_number], venue.seats[seat_id].room)
    )


def find_code_violations(
    plan: SeatingPlan, venue: Venue, students_by_id: dict[str, Student]
) -> list[tuple[str, str]]:
    """Findet Paare von Sitzplätzen desselben Raumes mit identischem Anzeigecode."""
    by_room_and_code: dict[tuple[str, str], list[str]] = defaultdict(list)
    for seat_id, matriculation_number in plan.assignments.items():
        code = students_by_id[matriculation_number].display_code
        if not code:
            continue
        by_room_and_code[(venue.seats[seat_id].room, code)].append(seat_id)

    violations: list[tuple[str, str]] = []
    for seat_ids in by_room_and_code.values():
        if len(seat_ids) < 2:
            continue
        seat_ids.sort()
        violations.extend(combinations(seat_ids, 2))
    return sorted(violations)


def find_all_violations(
    plan: SeatingPlan, venue: Venue, students_by_id: dict[str, Student]
) -> list[tuple[str, str]]:
    """Vereinigt alle Arten harter Platzierungsverletzungen.

    Gruppen- und Codeverletzungen betreffen stets zwei Plätze. Eine verletzte
    Raumvorgabe betrifft nur einen und erscheint daher als Paar ``(p, p)``.
    So zählt sie in der Fitness des Genetischen Algorithmus wie jede andere
    Verletzung, und die Reparatur versetzt den Prüfling auf diesem Platz.
    """
    return sorted(
        set(find_hard_violations(plan, venue, students_by_id))
        | set(find_code_violations(plan, venue, students_by_id))
        | {
            (seat_id, seat_id)
            for seat_id in find_room_requirement_violations(plan, venue, students_by_id)
        }
    )


def with_fixed_seats(
    students: list[Student], forced: list[ForcedAssignment]
) -> list[Student]:
    """Vermerkt bei jedem Prüfling mit Vorgabe aus F seinen festen Platz.

    Der Vermerk wandert mit dem Prüfling durch alle Verfahren und bis in den
    Bericht. ``find_hard_violations`` erkennt daran Paare, die die Planung
    ausdrücklich nebeneinander gesetzt hat.
    """
    seat_of = {f.matriculation_number: f"{f.room}:{f.seat_label}" for f in forced}
    if not seat_of:
        return students
    return [
        replace_student(s, fixed_seat=seat_of[s.matriculation_number])
        if s.matriculation_number in seat_of
        else s
        for s in students
    ]


def _same_group_neighbor_pairs(
    plan: SeatingPlan, venue: Venue, students_by_id: dict[str, Student]
) -> set[tuple[str, str]]:
    """Alle Paare benachbarter Plätze, die von derselben Seminargruppe besetzt sind."""
    pairs: set[tuple[str, str]] = set()
    for seat_id, matriculation_number in plan.assignments.items():
        group = students_by_id[matriculation_number].seminar_group
        for neighbor_id in venue.neighbors.get(seat_id, ()):
            neighbor_occupant = plan.assignments.get(neighbor_id)
            if neighbor_occupant is not None and students_by_id[neighbor_occupant].seminar_group == group:
                pairs.add(tuple(sorted((seat_id, neighbor_id))))
    return pairs


def _both_on_fixed_seats(
    pair: tuple[str, str], plan: SeatingPlan, students_by_id: dict[str, Student]
) -> bool:
    return all(students_by_id[plan.assignments[seat_id]].fixed_seat == seat_id for seat_id in pair)


def find_hard_violations(
    plan: SeatingPlan, venue: Venue, students_by_id: dict[str, Student]
) -> list[tuple[str, str]]:
    """Findet alle Paare benachbarter Sitzplätze, die von derselben Seminargruppe
    besetzt sind (Verletzung der Trennungs-Restriktion). Jedes Paar wird nur
    einmal, in sortierter Reihenfolge, zurückgegeben.

    Ausgenommen sind Paare, bei denen beide Prüflinge auf ihrem festen Platz
    aus F sitzen. Feste Plätze gehen der Trennung vor. Gegenüber allen anderen
    gilt die Trennung auch für diese beiden uneingeschränkt."""
    return sorted(
        pair
        for pair in _same_group_neighbor_pairs(plan, venue, students_by_id)
        if not _both_on_fixed_seats(pair, plan, students_by_id)
    )


def find_forced_neighbor_pairs(
    plan: SeatingPlan, venue: Venue, students_by_id: dict[str, Student]
) -> list[tuple[str, str]]:
    """Paare derselben Seminargruppe, die laut F bewusst nebeneinander sitzen.

    Sie sind keine Verletzung, sollen aber nicht still bleiben. Der Bericht
    führt sie deshalb gesondert auf."""
    return sorted(
        pair
        for pair in _same_group_neighbor_pairs(plan, venue, students_by_id)
        if _both_on_fixed_seats(pair, plan, students_by_id)
    )


def _rows(venue: Venue) -> dict[tuple[str, int], list[Seat]]:
    rows: dict[tuple[str, int], list[Seat]] = defaultdict(list)
    for seat in venue.seats.values():
        rows[(seat.room, seat.row)].append(seat)
    return rows


def fragmentation_cost(
    plan: SeatingPlan, venue: Venue, students_by_id: dict[str, Student]
) -> float:
    """C1: Anzahl distinkter (Seminargruppe, Raum)-Paare. Bestraft die
    Aufsplittung einer Gruppe über mehrere Räume."""
    group_rooms: set[tuple[str, str]] = set()
    for seat_id, matriculation_number in plan.assignments.items():
        student = students_by_id[matriculation_number]
        group_rooms.add((student.seminar_group, venue.seats[seat_id].room))
    return float(len(group_rooms))


SORT_SCALE = 1000.0
"""Zielbereich der Ordnungswerte. Beide Schlüsselarten werden darauf normiert,
damit das Gewicht $w_2$ nicht davon abhängt, ob nach Name oder nach
Matrikelnummer sortiert wird."""


def _name_sort_key(last_name: str) -> float:
    """Ordnungswert aus den ersten drei Buchstaben des Nachnamens (Basis 26).

    Umlaute werden über ``normalise_letter`` auf ihren Grundbuchstaben
    abgebildet, damit \"Müller\" zwischen \"Mueller\" und \"Mund\" einsortiert
    wird und nicht an den Anfang des Alphabets rutscht.
    """
    packed = 0
    for position in range(3):
        char = last_name[position] if position < len(last_name) else "A"
        letter = normalise_letter(char) or "A"
        packed = packed * 26 + (ord(letter) - ord("A"))
    return packed * SORT_SCALE / (26**3 - 1)


def _number_sort_key(value: str) -> float:
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return 0.0
    return (int(digits) % 100000) * SORT_SCALE / 99999


def sort_key(student: Student) -> float:
    """Ordnungswert eines Prüflings für die Sortierung benachbarter Plätze.

    Liegt ein Name vor, richtet sich die Sortierung nach dem Nachnamen. Das
    entspricht der alphabetischen Logik der Raumregeln aus Abschnitt 3.6: Ein
    Aushang der Form \"A-K in FE006\" ist nur dann hilfreich, wenn auch die
    Plätze innerhalb des Raumes alphabetisch fortlaufen. Fehlt der Name, dient
    die Matrikelnummer als Ersatz.
    """
    if student.last_name:
        return _name_sort_key(student.last_name)
    return _number_sort_key(student.matriculation_number)


def sorting_cost(
    plan: SeatingPlan, venue: Venue, students_by_id: dict[str, Student]
) -> float:
    """C2: Summe der Ordnungssprünge zwischen in einer Reihe direkt
    benachbarten, besetzten Sitzplätzen."""
    cost = 0.0
    for row_seats in _rows(venue).values():
        row_seats.sort(key=lambda s: s.col)
        previous_key: float | None = None
        for seat in row_seats:
            occupant = plan.assignments.get(seat.id)
            if occupant is None:
                previous_key = None
                continue
            key = sort_key(students_by_id[occupant])
            if previous_key is not None:
                cost += abs(key - previous_key)
            previous_key = key
    return cost


def compactness_gap_cost(plan: SeatingPlan, venue: Venue) -> float:
    """C3: Anzahl der Lücken innerhalb der belegten Spannweite jeder Sitzreihe.
    Eine Reihe mit Lücken zwischen besetzten Plätzen wird stärker bestraft als
    ein geschlossener Block."""
    cost = 0.0
    for row_seats in _rows(venue).values():
        occupied_cols = sorted(
            seat.col for seat in row_seats if seat.id in plan.assignments
        )
        if len(occupied_cols) < 2:
            continue
        span = occupied_cols[-1] - occupied_cols[0] + 1
        cost += span - len(occupied_cols)
    return cost


@dataclass(slots=True)
class Weights:
    """Gewichtungsfaktoren w_i der weichen Restriktionen in Z = sum_i w_i * C_i(x)."""

    fragmentation: float = 1.0
    sorting: float = 0.01
    gaps: float = 1.0


def objective(
    plan: SeatingPlan,
    venue: Venue,
    students_by_id: dict[str, Student],
    weights: Weights,
) -> float:
    """Berechnet die gewichtete Zielfunktion Z für einen gegebenen Sitzplan."""
    return (
        weights.fragmentation * fragmentation_cost(plan, venue, students_by_id)
        + weights.sorting * sorting_cost(plan, venue, students_by_id)
        + weights.gaps * compactness_gap_cost(plan, venue)
    )
