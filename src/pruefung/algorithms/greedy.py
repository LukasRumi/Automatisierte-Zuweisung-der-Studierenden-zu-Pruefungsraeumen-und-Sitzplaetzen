"""Baseline-Heuristik: ein klassischer Greedy-Algorithmus.

Vorgehen (siehe Abschnitt 4.5 der Arbeit, Variante A):

1. Sortierung: Die Studierenden werden nach Seminargruppe, dann nach dem
   Ordnungswert des Nachnamens und zuletzt nach Matrikelnummer sortiert, um zusammenhängende Blöcke zu
   begünstigen.
2. Sequenzielle Platzierung: Der Algorithmus iteriert über alle verfügbaren
   Sitzplätze in Reihenfolge des Einlesens.
3. Konfliktprüfung: Für den nächsten noch nicht platzierten Studierenden wird
   geprüft, ob der aktuelle Platz eine der harten Platzierungsrestriktionen
   verletzen würde -- die Trennung der Seminargruppen oder die Eindeutigkeit
   des Anzeigecodes innerhalb des Raumes.
4. Zuweisung: Ist der Platz konfliktfrei, wird der Studierende gesetzt und aus
   der Warteschlange entfernt. Andernfalls wird der nächste Platz geprüft,
   ohne die Warteschlange zu verändern.

Vordefinierte Zuweisungen F (z. B. aus Nachteilsausgleichen) werden vorab
fest gesetzt und bei der Konfliktprüfung wie reguläre Platzierungen behandelt.

Raumvorgaben engen den Wertebereich eines Prüflings auf einen Raum ein. Wer
für den Raum des aktuellen Platzes nicht in Frage kommt, ist für diesen Platz
kein Kandidat und wird übersprungen, ohne dass der Platz verloren geht. Damit
ein solcher Prüfling seinen Raum nicht verpasst, weil dieser vor seinem
Eintreffen in der Warteschlange voll ist, stehen Prüflinge mit Raumvorgabe am
Anfang der Warteschlange. Das ist die bekannte CSP-Heuristik, die Variable mit
dem kleinsten Wertebereich zuerst zu belegen.
"""

from __future__ import annotations

from pruefung.constraints import room_admits, seat_conflicts, sort_key
from pruefung.models import ForcedAssignment, SeatingPlan, Student, Venue


def apply_forced_assignments(
    forced: list[ForcedAssignment], students_by_id: dict[str, Student], venue: Venue
) -> SeatingPlan:
    """Setzt die Vorgaben aus $F$ um und prüft sie auf Widersprüche.

    Die Vorgaben sind eine harte Restriktion und werden von den Verfahren
    unverändert übernommen. Sind sie untereinander unverträglich, entstünde
    daraus ein Sitzplan, der eine Restriktion verletzt, ohne dass ein Verfahren
    dafür verantwortlich wäre. Solche Eingaben werden daher hier zurückgewiesen
    statt stillschweigend übernommen.
    """
    plan = SeatingPlan()
    seen: set[str] = set()
    for entry in forced:
        if entry.matriculation_number not in students_by_id:
            raise ValueError(
                f"Vorgegebene Zuweisung verweist auf unbekannte Matrikelnummer '{entry.matriculation_number}'."
            )
        if entry.matriculation_number in seen:
            raise ValueError(
                f"Für Matrikelnummer '{entry.matriculation_number}' wurden mehrere "
                "Sitzplätze vorgegeben."
            )
        seen.add(entry.matriculation_number)
        seat_id = f"{entry.room}:{entry.seat_label}"
        if seat_id not in venue.seats:
            raise ValueError(f"Vorgegebene Zuweisung verweist auf unbekannten Sitzplatz '{seat_id}'.")
        if seat_id in venue.reserved:
            raise ValueError(
                f"Sitzplatz '{seat_id}' ist als Reserveplatz freigehalten und kann "
                "nicht vorgegeben werden."
            )
        if seat_id in plan.assignments:
            raise ValueError(f"Sitzplatz '{seat_id}' wurde mehrfach vorgegeben.")
        plan.assignments[seat_id] = entry.matriculation_number

    # Zwei Vorgaben derselben Seminargruppe auf benachbarten Plätzen sind
    # zulässig. Die Planung hat sie ausdrücklich so gesetzt, und feste Plätze
    # gehen der Trennung vor (siehe ``constraints.find_hard_violations``). Der
    # Bericht führt solche Paare gesondert auf.

    # Zwei Vorgaben mit gleichem Anzeigecode im selben Raum widersprechen
    # einander. Kein Verfahren könnte den Konflikt lösen, ohne eine Vorgabe
    # zu verletzen. Ein leerer Code unterliegt der Restriktion nicht.
    by_room_and_code: dict[tuple[str, str], str] = {}
    for seat_id, matriculation_number in plan.assignments.items():
        code = students_by_id[matriculation_number].display_code
        if not code:
            continue
        key = (venue.seats[seat_id].room, code)
        other = by_room_and_code.get(key)
        if other is not None:
            raise ValueError(
                f"Die Vorgaben für '{other}' und '{matriculation_number}' setzen zwei "
                f"Prüflinge mit dem Anzeigecode '{code}' in den Raum '{key[0]}'."
            )
        by_room_and_code[key] = matriculation_number
    return plan


def _sort_key(student: Student) -> tuple[bool, str, float, str]:
    """Sortiert nach Seminargruppe und innerhalb dieser nach demselben
    Ordnungswert, den auch die Kostenfunktion $C_2$ verwendet -- also nach
    Nachname, sofern vorhanden. Prüflinge mit Raumvorgabe stehen vorn."""
    return (
        not student.required_room,
        student.seminar_group,
        sort_key(student),
        student.matriculation_number,
    )


def greedy_assign(
    students: list[Student],
    venue: Venue,
    forced: list[ForcedAssignment] | None = None,
) -> SeatingPlan:
    """Erzeugt einen Sitzplan mittels der Greedy-Baseline-Heuristik."""
    students_by_id = {s.matriculation_number: s for s in students}
    plan = apply_forced_assignments(forced or [], students_by_id, venue)

    already_seated = set(plan.assignments.values())
    queue = sorted(
        (s for s in students if s.matriculation_number not in already_seated),
        key=_sort_key,
    )

    for seat_id in venue.seats_in_reading_order():
        if seat_id in plan.assignments:
            continue
        if not queue:
            break
        # Der vorderste Prüfling, für den der Raum dieses Platzes zulässig ist.
        # Ohne Raumvorgaben ist das stets der Kopf der Warteschlange.
        room = venue.seats[seat_id].room
        position = next(
            (i for i, candidate in enumerate(queue) if room_admits(candidate, room)), None
        )
        if position is None:
            continue
        student = queue[position]
        if not seat_conflicts(seat_id, student, plan, students_by_id, venue):
            plan.assignments[seat_id] = student.matriculation_number
            del queue[position]

    plan.unassigned = [s.matriculation_number for s in queue]
    return plan
