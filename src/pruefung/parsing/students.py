"""Einlesen der Studierendendaten aus CSV-Dateien.

Unterstützt werden zwei Varianten:

1. **Format ohne Kopfzeile** (Format der realen Teilnehmerliste), mit
   Semikolon getrennt. Die Matrikelnummern im Beispiel sind ausgedacht::

       847891;25INB-1;A49124, 1191870767;
       853261;25INB-2;P148885, 192365805;NTA

   Die Spalten sind positionsfest: Matrikelnummer, Seminargruppe, Name in der
   Form ``"Nachname, Vorname"`` und anschließend Vermerke. Das Kürzel ``NTA``
   markiert dort einen Nachteilsausgleich. Die Namen liegen anonymisiert vor,
   weshalb sie Ziffern enthalten. Jeder Nachname beginnt aber weiterhin mit
   einem Buchstaben. Angenommen wird, dass dies der echte Anfangsbuchstabe ist,
   denn die Liste ist danach sortiert und die Seminargruppen passen zu ihm.

2. **Format mit Kopfzeile**, mit den Spalten ``matrikelnummer``,
   ``seminargruppe`` sowie optional ``name`` und ``nachteilsausgleich``.

Für das Feld des Nachteilsausgleichs gilt in beiden Varianten dieselbe
Interpretation:

* ``NTA``                  -> Nachteilsausgleich (Platzierung im NTA-Raum).
* ``<Raum>:<Sitzplatz>``   -> zwingend vorgegebene Zuweisung (s, p) ∈ F.
* ``<Raum>``               -> Raumvorgabe (s, r) ∈ F_R, der Platz bleibt frei wählbar.
* sonstiger Text           -> reine Freitext-Notiz ohne algorithmische Wirkung.

Ein bloßer Raumname lässt sich beim Einlesen noch nicht von einer Notiz
unterscheiden, da die Räume erst später geladen werden. Er bleibt hier daher
als Vermerk stehen und wird von ``pruefung.requirements`` aufgelöst.

Das Trennzeichen (Komma oder Semikolon) wird automatisch erkannt.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from pruefung.models import ForcedAssignment, Student

NTA_FLAG = "NTA"

_FORCED_PATTERN = re.compile(r"^\s*([^:]+):(.+?)\s*$")


def _detect_delimiter(lines: list[str]) -> str:
    """Bestimmt das Trennzeichen einer CSV-Datei (Semikolon oder Komma).

    ``csv.Sniffer`` ist hier ungeeignet, weil die realen Teilnehmerdaten innerhalb
    eines Feldes Kommas enthalten (z. B. ``A49124, 1191870767``). Gewählt wird
    daher das Zeichen, das in jeder Zeile vorkommt und dabei die konstanteste
    Spaltenzahl erzeugt; bei Gleichstand gewinnt das Zeichen mit den meisten
    Vorkommen je Zeile.
    """
    sample = [line for line in lines[:50] if line.strip()]
    best = ","
    best_score: tuple[int, int] | None = None
    for candidate in (";", ","):
        counts = [line.count(candidate) for line in sample]
        if not counts or min(counts) == 0:
            continue
        score = (len(set(counts)), -min(counts))
        if best_score is None or score < best_score:
            best_score = score
            best = candidate
    return best


def _extract_accommodation(fields: list[str]) -> str:
    """Bestimmt aus den Restspalten einer Zeile den Wert des Nachteilsausgleichs.

    Priorität: ein exaktes ``NTA``-Kürzel, danach ein ``<Raum>:<Sitzplatz>``-Muster,
    andernfalls der erste nicht-leere Wert als Freitext-Notiz.
    """
    values = [field.strip() for field in fields if field.strip()]
    for value in values:
        if value.upper() == NTA_FLAG:
            return NTA_FLAG
    for value in values:
        if _FORCED_PATTERN.match(value):
            return value
    return values[0] if values else ""


def _build_forced(matriculation_number: str, accommodation: str) -> ForcedAssignment | None:
    if accommodation.upper() == NTA_FLAG:
        return None
    match = _FORCED_PATTERN.match(accommodation)
    if not match:
        return None
    room, seat_label = match.groups()
    return ForcedAssignment(
        matriculation_number=matriculation_number, room=room.strip(), seat_label=seat_label.strip()
    )


def _row_to_student(
    matriculation_number: str, seminar_group: str, name: str, note_fields: list[str]
) -> tuple[Student, ForcedAssignment | None]:
    accommodation = _extract_accommodation(note_fields)
    student = Student(
        matriculation_number=matriculation_number,
        seminar_group=seminar_group,
        name=name.strip(),
        accommodation=accommodation,
    )
    return student, _build_forced(matriculation_number, accommodation)


def _column_indices(
    header_row: list[str], path: Path
) -> tuple[int, int, int | None, int | None]:
    normalized = [name.strip().lower() for name in header_row]
    for required in ("matrikelnummer", "seminargruppe"):
        if required not in normalized:
            raise ValueError(f"Pflichtspalte '{required}' fehlt in '{path}'.")
    return (
        normalized.index("matrikelnummer"),
        normalized.index("seminargruppe"),
        normalized.index("name") if "name" in normalized else None,
        normalized.index("nachteilsausgleich") if "nachteilsausgleich" in normalized else None,
    )


def parse_students_csv(path: Path | str) -> tuple[list[Student], list[ForcedAssignment]]:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    delimiter = _detect_delimiter(lines)

    rows = [
        row
        for row in csv.reader(lines, delimiter=delimiter)
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        return [], []

    # Eine Matrikelnummer besteht ausschließlich aus Ziffern; alles andere in der
    # ersten Zelle deutet auf eine Kopfzeile hin.
    has_header = not rows[0][0].strip().isdigit()

    if has_header:
        number_index, group_index, name_index, note_index = _column_indices(rows[0], path)
        data_rows = rows[1:]
    else:
        # Positionsfestes Format ohne Kopfzeile: Matrikelnummer; Seminargruppe; Name; Vermerke.
        number_index, group_index, name_index, note_index = 0, 1, 2, None
        data_rows = rows

    students: list[Student] = []
    forced: list[ForcedAssignment] = []

    for row in data_rows:
        if len(row) <= max(number_index, group_index):
            continue
        matriculation_number = row[number_index].strip()
        seminar_group = row[group_index].strip()
        if not matriculation_number or not seminar_group:
            continue

        name = row[name_index] if name_index is not None and name_index < len(row) else ""

        if note_index is not None:
            note_fields = [row[note_index]] if note_index < len(row) else []
        elif name_index is not None:
            note_fields = row[name_index + 1 :]
        else:
            note_fields = row[group_index + 1 :]

        student, forced_entry = _row_to_student(matriculation_number, seminar_group, name, note_fields)
        students.append(student)
        if forced_entry:
            forced.append(forced_entry)

    # Eine doppelte Matrikelnummer wuerde still zu zwei Eintraegen fuehren, von
    # denen einer spaeter den anderen verdraengt. Der Fehler faellt dann erst
    # auf, wenn jemand am Pruefungstag keinen Platz hat.
    seen: set[str] = set()
    duplicates = sorted(
        {s.matriculation_number for s in students
         if s.matriculation_number in seen or seen.add(s.matriculation_number)}
    )
    if duplicates:
        raise ValueError(
            f"Die Matrikelnummern {', '.join(duplicates)} kommen in '{path}' "
            "mehrfach vor."
        )

    return students, forced
