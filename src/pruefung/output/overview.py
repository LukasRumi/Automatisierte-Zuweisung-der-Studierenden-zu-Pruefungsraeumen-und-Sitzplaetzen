"""Interne Pläne für die Prüfungsaufsicht.

Im Unterschied zum Aushangplan (siehe ``pruefung.output.plans``) sind diese
Pläne nicht für den öffentlichen Aushang bestimmt. Sie nennen daher Klarnamen
und vollständige Matrikelnummern.

Erzeugt werden zwei Arten, einzeln und zusätzlich in einer gemeinsamen Datei:

* Je Raum ein Plan, der die Sitzordnung räumlich abbildet und die Lage der
  Tafel markiert, gefolgt von einer nach Sitzplatz sortierten Liste. Das ist
  die Form, die am Prüfungstag im Raum gebraucht wird.
* Zusätzlich eine alphabetische Gesamtliste über alle Räume. Sie beantwortet
  die Frage, wo ein bestimmter Prüfling sitzt, wenn er am falschen Raum steht.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from pruefung.models import SeatingPlan, Student, Venue
from pruefung.output.pdf import write_documents_pdf, write_pdf
from pruefung.output.seatmap import render_seat_map, seat_entry

UNASSIGNED_MARKER = "-- kein Platz --"
CELL_WIDTH = 3
"""Breite einer Kartenzelle. Sitzplatzbezeichnungen wie ``A1`` oder ``C12``
umfassen zwei bis drei Zeichen."""


def _sort_key(student: Student) -> tuple[str, str]:
    """Alphabetisch nach Name; Studierende ohne Namen ans Ende, dann nach Matrikelnummer."""
    return (student.name.casefold() or "￿", student.matriculation_number)


def render_overview(
    venue: Venue, plan: SeatingPlan, students: list[Student]
) -> str:
    """Erzeugt die alphabetische Gesamtliste über alle Räume."""
    seat_of: dict[str, str] = {
        matriculation_number: seat_id for seat_id, matriculation_number in plan.assignments.items()
    }

    name_width = max((len(s.name) for s in students if s.name), default=0)
    name_width = max(name_width, len("Name")) + 2

    header = "Übersichtsplan der Prüfung"
    lines = [header, "=" * len(header), ""]
    lines.append(
        f"{'Name':<{name_width}}{'Matr.-Nr.':<12}{'Seminargruppe':<16}{'Raum':<12}{'Platz':<8}"
    )
    lines.append("-" * (name_width + 48))

    without_seat: list[Student] = []
    for student in sorted(students, key=_sort_key):
        seat_id = seat_of.get(student.matriculation_number)
        if seat_id is None:
            without_seat.append(student)
            continue
        seat = venue.seats[seat_id]
        lines.append(
            f"{student.name:<{name_width}}{student.matriculation_number:<12}"
            f"{student.seminar_group:<16}{seat.room:<12}{seat.label:<8}"
        )

    for student in without_seat:
        lines.append(
            f"{student.name:<{name_width}}{student.matriculation_number:<12}"
            f"{student.seminar_group:<16}{UNASSIGNED_MARKER:<20}"
        )

    lines.append("")
    lines.append(f"Zugewiesen: {len(plan.assignments)} von {len(students)} Prüflingen")
    if without_seat:
        lines.append(f"Ohne Platz: {len(without_seat)}")

    return "\n".join(lines) + "\n"


def render_room_overview(
    room_name: str,
    venue: Venue,
    plan: SeatingPlan,
    students: list[Student],
    rule: str | None = None,
) -> str:
    """Erzeugt den Aufsichtsplan eines einzelnen Raumes.

    Die Karte zeigt die Sitzplatzbezeichnungen, die darunterstehende Liste
    ordnet ihnen die Prüflinge zu. Beide sind nach derselben Lesereihenfolge
    angeordnet, sodass sich ein Name in der Liste unmittelbar auf der Karte
    wiederfinden lässt.
    """
    by_id = {s.matriculation_number: s for s in students}

    header = f"Aufsichtsplan Raum {room_name}"
    lines = [header, "=" * len(header), ""]
    if rule:
        lines.append(f"Zuordnung: {rule}")
        lines.append("")

    entry = seat_entry(venue, plan, lambda _: "")
    labelled = {
        seat_id: venue.seats[seat_id].label
        for seat_id in venue.rooms[room_name].seat_ids
    }
    lines.extend(
        render_seat_map(
            room_name,
            venue,
            lambda seat_id: labelled[seat_id]
            if seat_id in plan.assignments
            else entry(seat_id),
            CELL_WIDTH,
        )
    )
    lines.append("")

    occupied = [
        (seat_id, by_id[plan.assignments[seat_id]])
        for seat_id in venue.rooms[room_name].seat_ids
        if seat_id in plan.assignments
    ]
    name_width = max((len(s.name) for _, s in occupied if s.name), default=0)
    name_width = max(name_width, len("Name")) + 2

    lines.append(
        f"{'Platz':<8}{'Name':<{name_width}}{'Matr.-Nr.':<12}{'Seminargruppe':<16}"
    )
    lines.append("-" * (name_width + 36))
    for seat_id, student in occupied:
        lines.append(
            f"{venue.seats[seat_id].label:<8}{student.name:<{name_width}}"
            f"{student.matriculation_number:<12}{student.seminar_group:<16}"
        )

    seat_count = len(venue.assignable_in(room_name))
    lines.append("")
    lines.append(f"Belegt: {len(occupied)} von {seat_count} zuweisbaren Plätzen")
    return "\n".join(lines) + "\n"


def write_overview(
    venue: Venue,
    plan: SeatingPlan,
    students: list[Student],
    output_dir: Path | str,
    formats: Sequence[str] = ("text", "pdf"),
    rules: Mapping[str, str] | None = None,
) -> list[Path]:
    """Schreibt die Aufsichtspläne je Raum sowie die Gesamtliste.

    Daneben entsteht ``sitzplatzzuordnung.pdf`` mit allen internen Unterlagen
    in einer Datei, zuerst die Räume und dahinter die Gesamtliste. Die
    Aufsicht eines Raumes trifft oft erst kurz vor der Prüfung ein, und dann
    soll sie ein Dokument in die Hand bekommen und nicht fünf einzelne
    Dateien. Getrennt wird der Stapel entlang der Seiten, die Gesamtliste
    bleibt am Ende für die Prüfungsorganisation.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    alle: list[list[str]] = []

    for room_name in sorted(venue.rooms):
        content = render_room_overview(
            room_name, venue, plan, students, (rules or {}).get(room_name)
        )
        if "text" in formats:
            path = output_dir / f"aufsicht_{room_name}.txt"
            path.write_text(content, encoding="utf-8")
            written.append(path)
        if "pdf" in formats:
            alle.append(content.splitlines())
            written.append(
                write_pdf(
                    output_dir / f"aufsicht_{room_name}.pdf",
                    content.splitlines(),
                    f"Aufsichtsplan Raum {room_name}",
                    landscape=True,
                )
            )

    content = render_overview(venue, plan, students)
    if "text" in formats:
        path = output_dir / "uebersichtsplan.txt"
        path.write_text(content, encoding="utf-8")
        written.append(path)
    if "pdf" in formats:
        alle.append(content.splitlines())
        written.append(
            write_pdf(
                output_dir / "uebersichtsplan.pdf",
                content.splitlines(),
                "Übersichtsplan der Prüfung",
            )
        )

    if alle:
        # Im Querformat, weil die Raumkarten der Aufsichtspläne es verlangen.
        # Die Gesamtliste ist schmaler und verträgt es ohne Umbruch.
        written.append(
            write_documents_pdf(
                output_dir / "sitzplatzzuordnung.pdf",
                alle,
                "Sitzplatzzuordnung zur Prüfung",
                landscape=True,
            )
        )
    return written
