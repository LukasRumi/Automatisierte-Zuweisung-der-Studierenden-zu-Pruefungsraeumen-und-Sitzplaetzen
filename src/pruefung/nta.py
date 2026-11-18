"""Sonderbehandlung von Studierenden mit Nachteilsausgleich (NTA).

Für Prüflinge mit Nachteilsausgleich steht ein eigener Raum zur Verfügung.
Dieser Raum unterliegt einer harten Restriktion in beide Richtungen:

* Studierende mit NTA-Vermerk dürfen ausschließlich in diesem Raum sitzen.
* Studierende ohne NTA-Vermerk dürfen dort nicht platziert werden.

Formal entspricht das einer Einschränkung des Wertebereichs (der Domäne) der
Entscheidungsvariablen: für einen Studierenden s ist nur noch eine Teilmenge
D(s) ⊆ P zulässig. Innerhalb des NTA-Raums werden die Plätze in
Lesereihenfolge vergeben, sodass die Belegung an den vordersten Reihen beginnt.
"""

from __future__ import annotations

from pruefung.models import SeatingPlan, Student, Venue

NTA_FLAG = "NTA"


def is_nta(student: Student) -> bool:
    return student.accommodation.strip().upper() == NTA_FLAG


def split_by_nta_flag(students: list[Student]) -> tuple[list[Student], list[Student]]:
    """Teilt die Studierenden in (NTA-Prüflinge, reguläre Prüflinge)."""
    nta_students = [s for s in students if is_nta(s)]
    regular_students = [s for s in students if not is_nta(s)]
    return nta_students, regular_students


def find_nta_rooms(venue: Venue, override: str | None = None) -> list[str]:
    """Ermittelt die für Nachteilsausgleiche vorgesehenen Räume.

    Ohne explizite Vorgabe greift die Namenskonvention der Raumdateien: ein
    Raum gilt als NTA-Raum, wenn sein Name (ohne Beachtung der Groß-/
    Kleinschreibung) ``nta`` lautet oder auf ``_nta`` bzw. ``-nta`` endet.
    """
    if override:
        if override not in venue.rooms:
            raise ValueError(f"NTA-Raum '{override}' wurde nicht gefunden.")
        return [override]

    return [
        name
        for name in sorted(venue.rooms)
        if name.lower() == "nta" or name.lower().endswith(("_nta", "-nta"))
    ]


def find_nta_violations(
    plan: SeatingPlan,
    venue: Venue,
    students_by_id: dict[str, Student],
    nta_rooms: list[str],
) -> list[str]:
    """Findet Sitzplätze, deren Belegung die harte NTA-Raumrestriktion verletzt.

    Verletzt ist sie, wenn ein Studierender mit NTA-Vermerk außerhalb eines
    NTA-Raumes sitzt oder ein Studierender ohne NTA-Vermerk in einem solchen.
    """
    nta_room_set = set(nta_rooms)
    violations = [
        seat_id
        for seat_id, matriculation_number in plan.assignments.items()
        if is_nta(students_by_id[matriculation_number]) != (venue.seats[seat_id].room in nta_room_set)
    ]
    return sorted(violations)


def subvenue(venue: Venue, room_names: set[str], *, include: bool) -> Venue:
    """Erzeugt eine auf bestimmte Räume reduzierte Sicht auf den Prüfungsort.

    Mit ``include=True`` bleiben nur die genannten Räume erhalten, mit
    ``include=False`` werden sie ausgeschlossen. Die Nachbarschaften N_p werden
    dabei nicht neu berechnet, sondern lediglich auf die verbleibenden
    Sitzplätze eingeschränkt -- sie bestehen ohnehin nur innerhalb eines Raumes.
    """
    rooms = {
        name: room for name, room in venue.rooms.items() if (name in room_names) == include
    }
    seats = {seat_id: seat for seat_id, seat in venue.seats.items() if seat.room in rooms}
    neighbors = {seat_id: venue.neighbors[seat_id] & seats.keys() for seat_id in seats}
    return Venue(
        rooms=rooms,
        seats=seats,
        neighbors=neighbors,
        reserved=frozenset(s for s in venue.reserved if s in seats),
    )
