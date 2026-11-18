"""Datenmodelle für das Zuweisungsproblem.

Die Klassen bilden die in der Modellierung (siehe Kapitel 3 der Arbeit)
definierten Mengen ab:

* ``Student``  entspricht einem Element aus S, ``g(s)`` ist ``Student.seminar_group``.
* ``Seat``     entspricht einem Element aus P, ``r(p)`` ist ``Seat.room``.
* ``Room``     entspricht einem Element aus R.
* ``Venue``    bündelt alle Räume und Sitzplätze und stellt r(p) sowie N_p bereit.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

_UMLAUTS = {
    "Ä": "A", "ä": "A",
    "Ö": "O", "ö": "O",
    "Ü": "U", "ü": "U",
    "ß": "S",
}


def normalise_letter(char: str) -> str | None:
    """Bildet ein Zeichen auf einen Buchstaben von A bis Z ab.

    Umlaute werden nach DIN 5007-1 auf ihren Grundbuchstaben zurückgeführt, Ä
    auf A, Ö auf O und Ü auf U. Ohne diese Abbildung fielen deutsche Namen aus
    dem Buchstabenbereich heraus, auf dem die Einteilungen und die Sortierung
    beruhen. Zeichen ohne Entsprechung, etwa Ziffern, ergeben ``None``.
    """
    if not char:
        return None
    letter = _UMLAUTS.get(char) or char.upper()
    if len(letter) != 1 or not ("A" <= letter <= "Z"):
        return None
    return letter


@dataclass(frozen=True, slots=True)
class Student:
    """Ein Studierender s ∈ S."""

    matriculation_number: str
    seminar_group: str
    name: str = ""
    """Name in der Form ``"Nachname, Vorname"``; erscheint ausschließlich auf dem
    internen Übersichtsplan, nie auf dem öffentlichen Aushang."""
    accommodation: str = ""
    display_code: str = ""
    """Die auf dem Aushangplan sichtbaren letzten Ziffern der Matrikelnummer;
    muss je Raum eindeutig sein."""
    required_room: str = ""
    """Raumvorgabe (s, r) ∈ F_R: Der Prüfling muss in diesem Raum sitzen, auf
    welchem Platz, bleibt dem Verfahren überlassen. Leer, wenn keine Vorgabe
    besteht. Gesetzt wird sie von ``pruefung.requirements``, da erst dort die
    Raumnamen bekannt sind."""
    fixed_seat: str = ""
    """Fester Platz (s, p) ∈ F als Platzkennung ``"<Raum>:<Label>"``. Leer, wenn
    keine Vorgabe besteht. Gesetzt wird er von ``constraints.with_fixed_seats``.
    Sitzen zwei Prüflinge derselben Gruppe beide auf ihrem festen Platz, gilt die
    Trennung zwischen ihnen nicht."""

    @property
    def id(self) -> str:
        """Eindeutiger Schlüssel, die volle Matrikelnummer."""
        return self.matriculation_number

    @property
    def last_name(self) -> str:
        """Der Namensteil vor dem Komma; leer, wenn kein Name vorliegt."""
        return self.name.split(",", 1)[0].strip()


@dataclass(frozen=True, slots=True)
class ForcedAssignment:
    """Ein zwingend vorgegebenes Paar (s, p) ∈ F, z. B. aufgrund eines Nachteilsausgleichs."""

    matriculation_number: str
    room: str
    seat_label: str


@dataclass(frozen=True, slots=True)
class Seat:
    """Ein physischer Sitzplatz p ∈ P."""

    id: str
    """Global eindeutige Kennung der Form ``"<Raum>:<Label>"``."""
    room: str
    """r(p): der Raum, in dem sich der Platz befindet."""
    label: str
    """Menschenlesbare, raumlokale Bezeichnung, z. B. ``"A3"``."""
    row: int
    col: int
    x: float
    """Feingranulare x-Koordinate für die Nachbarschaftsberechnung."""
    y: float
    """Feingranulare y-Koordinate für die Nachbarschaftsberechnung."""


@dataclass(slots=True)
class Room:
    """Ein Prüfungsraum r ∈ R."""

    name: str
    grid: list[str]
    """Die eingelesenen, unveränderten Zeilen des ASCII-Rasters."""
    seat_ids: list[str] = field(default_factory=list)
    """Sitzplätze dieses Raumes in Lesereihenfolge (Zeile für Zeile, links nach rechts)."""


@dataclass(slots=True)
class Venue:
    """Container für alle Räume und Sitzplätze einer Prüfung sowie deren Nachbarschaften N_p."""

    rooms: dict[str, Room]
    seats: dict[str, Seat]
    neighbors: dict[str, frozenset[str]]
    reserved: frozenset[str] = field(default_factory=frozenset)
    """Sitzplätze, die als Reserve freibleiben. Sie erscheinen weiterhin auf dem
    Aushangplan, werden aber nie vergeben."""

    def seats_in_reading_order(self) -> list[str]:
        """Alle vergebbaren Sitzplätze, sortiert nach Raum und Leseposition.

        Reservierte Plätze sind ausgenommen: Sie stehen der Zuweisung nicht zur
        Verfügung, bleiben aber Teil des Raumes.
        """
        ordered: list[str] = []
        for room_name in sorted(self.rooms):
            ordered.extend(
                seat_id
                for seat_id in self.rooms[room_name].seat_ids
                if seat_id not in self.reserved
            )
        return ordered

    def assignable_in(self, room_name: str) -> list[str]:
        """Die vergebbaren Sitzplätze eines Raumes in Lesereihenfolge."""
        return [
            seat_id
            for seat_id in self.rooms[room_name].seat_ids
            if seat_id not in self.reserved
        ]


@dataclass(slots=True)
class SeatingPlan:
    """Eine konkrete Belegung, d. h. eine Realisierung der Entscheidungsvariablen x_{s,p}."""

    assignments: dict[str, str] = field(default_factory=dict)
    """Sitzplatz-ID -> Matrikelnummer des zugewiesenen Studierenden."""
    unassigned: list[str] = field(default_factory=list)
    """Matrikelnummern von Studierenden, die keinem Platz zugewiesen werden konnten."""

    def seat_of(self, matriculation_number: str) -> str | None:
        for seat_id, occupant in self.assignments.items():
            if occupant == matriculation_number:
                return seat_id
        return None

    def student_at(self, seat_id: str) -> str | None:
        return self.assignments.get(seat_id)

    def copy(self) -> "SeatingPlan":
        return SeatingPlan(dict(self.assignments), list(self.unassigned))


def replace_student(student: Student, **changes: object) -> Student:
    """Kleine Hilfsfunktion, um ein neues, unveränderliches ``Student``-Objekt zu erzeugen."""
    return dataclasses.replace(student, **changes)
