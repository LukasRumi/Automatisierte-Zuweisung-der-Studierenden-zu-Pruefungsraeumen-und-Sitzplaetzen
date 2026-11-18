"""Raumvorgaben: Prüflinge, die in einem bestimmten Raum sitzen müssen.

Die Aufgabenstellung verlangt neben festen Plätzen auch Vorgaben, nach denen
bestimmte Studierende in bestimmten Räumen sitzen. Eine Raumvorgabe legt nur
den Raum fest, den Platz wählt das Verfahren. Formal engt sie den Wertebereich
D(s) auf die Plätze dieses Raumes ein (siehe Abschnitt 3.2 der Arbeit).

**Eingabe.** Im Vermerkfeld der Teilnehmerliste steht der bloße Raumname,
etwa ``FE006``. Beim Einlesen der Liste sind die Räume noch nicht bekannt.
Deshalb gilt ein Vermerk erst hier als Raumvorgabe, sobald er einem Raumnamen
entspricht. Groß- und Kleinschreibung spielt dabei keine Rolle.

Ein Vermerk, der keinem Raum entspricht, bleibt eine Notiz. Ein Tippfehler im
Raumnamen fiele so nicht auf. ``ineffective_notes`` benennt deshalb alle
Vermerke, die ohne Wirkung geblieben sind, damit der Bericht sie aufführen
kann.
"""

from __future__ import annotations

from collections import Counter

from pruefung.models import ForcedAssignment, Student, Venue, replace_student
from pruefung.nta import is_nta


def resolve_room_requirements(
    students: list[Student],
    venue: Venue,
    nta_rooms: list[str],
    forced: list[ForcedAssignment],
) -> list[Student]:
    """Setzt ``required_room`` für jeden Prüfling, dessen Vermerk ein Raumname ist.

    Eine bereits gesetzte Vorgabe bleibt erhalten und wird nur geprüft.
    Zurückgewiesen werden Vorgaben, die keine Lösung zulassen können:

    * ein unbekannter Raum,
    * ein Raum, den die Raumbindung der Nachteilsausgleiche dem Prüfling
      verschließt (der Wertebereich wäre leer),
    * ein fester Platz in einem anderen Raum,
    * mehr gebundene Prüflinge, als der Raum Plätze bietet.

    Ob alle gebundenen Prüflinge auch unter der Trennung der Seminargruppen
    Platz finden, lässt sich vorab nicht entscheiden. Das zeigt erst der Lauf.
    """
    by_lower = {name.lower(): name for name in venue.rooms}
    nta = set(nta_rooms)
    forced_room = {f.matriculation_number: f.room for f in forced}

    resolved: list[Student] = []
    for student in students:
        room = student.required_room
        if not room and not is_nta(student):
            room = by_lower.get(student.accommodation.strip().lower(), "")
        if not room:
            resolved.append(student)
            continue

        number = student.matriculation_number
        if room not in venue.rooms:
            raise ValueError(f"Die Raumvorgabe für '{number}' nennt den unbekannten Raum '{room}'.")
        if is_nta(student) and room not in nta:
            raise ValueError(
                f"'{number}' hat einen Nachteilsausgleich und muss in einem NTA-Raum "
                f"sitzen, die Raumvorgabe nennt aber '{room}'."
            )
        if not is_nta(student) and room in nta:
            raise ValueError(
                f"Die Raumvorgabe für '{number}' nennt den NTA-Raum '{room}', der "
                "Prüfling hat aber keinen Nachteilsausgleich."
            )
        if number in forced_room and forced_room[number] != room:
            raise ValueError(
                f"Für '{number}' ist der Raum '{room}' vorgegeben, zugleich aber ein "
                f"fester Platz in '{forced_room[number]}'."
            )
        resolved.append(replace_student(student, required_room=room))

    bound = Counter(s.required_room for s in resolved if s.required_room)
    required_ids = {s.matriculation_number for s in resolved if s.required_room}
    for number, room in forced_room.items():
        if number not in required_ids:
            bound[room] += 1
    for room, count in sorted(bound.items()):
        if room not in venue.rooms:
            # Ein fester Platz in einem unbekannten Raum wird bei der
            # Umsetzung von F mit einer eigenen Meldung zurückgewiesen.
            continue
        capacity = len(venue.assignable_in(room))
        if count > capacity:
            raise ValueError(
                f"Für Raum '{room}' liegen {count} Raum- und Platzvorgaben vor, er "
                f"bietet aber nur {capacity} vergebbare Plätze."
            )
    return resolved


def ineffective_notes(
    students: list[Student], forced: list[ForcedAssignment]
) -> dict[str, str]:
    """Vermerke, die weder Nachteilsausgleich noch Platz- oder Raumvorgabe sind."""
    forced_ids = {f.matriculation_number for f in forced}
    return {
        s.matriculation_number: s.accommodation.strip()
        for s in students
        if s.accommodation.strip()
        and not is_nta(s)
        and not s.required_room
        and s.matriculation_number not in forced_ids
    }
