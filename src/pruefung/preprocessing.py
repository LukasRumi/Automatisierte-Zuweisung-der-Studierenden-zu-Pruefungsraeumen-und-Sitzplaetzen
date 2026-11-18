"""Vorverarbeitung der Studierendendaten vor der Zuweisung.

Auf dem Aushangplan steht jeder Prüfling nur mit den letzten Ziffern seiner
Matrikelnummer, dem ``display_code``. Das wahrt die Anonymität, verlangt aber,
dass der Code innerhalb eines Raumes eindeutig bleibt. Andernfalls könnten zwei
Studierende ihren Platz nicht auseinanderhalten.

Gezeigt werden bewusst die echten Endziffern. Die letzte Ziffer ist auf der
realen Instanz fast immer dieselbe und unterscheidet kaum. Sie wegzulassen
spräche für eine Stelle weniger, doch dann fände niemand seinen Code, der
nach seinen Endziffern sucht.

Wie viele Stellen nötig sind, hängt von der konkreten Teilnehmerliste ab und
wird über ``minimal_code_length`` bestimmt.
"""

from __future__ import annotations

from collections import Counter

from pruefung.models import Student, replace_student

DEFAULT_CODE_LENGTHS = (2, 3, 4)
"""Stellenzahlen des Anzeigecodes, die das Werkzeug von selbst prüft, in
aufsteigender Reihenfolge. Jede weitere Stelle verrät mehr von der
Matrikelnummer. Mehr als vier Stellen lassen sich deshalb nur ausdrücklich
über ``--code-digits`` verlangen."""


def preprocess_students(students: list[Student], code_length: int | None = None) -> list[Student]:
    """Setzt optional den Anzeigecode auf die letzten ``code_length`` Stellen."""
    if code_length is None:
        return list(students)
    return apply_code_length(students, code_length)


def apply_code_length(students: list[Student], code_length: int) -> list[Student]:
    """Setzt den Anzeigecode auf die letzten ``code_length`` Stellen."""
    return [
        replace_student(s, display_code=s.matriculation_number[-code_length:])
        for s in students
    ]


def code_multiplicities(students: list[Student], code_length: int) -> Counter[str]:
    """Zählt, wie oft jeder Anzeigecode bei der gegebenen Stellenzahl vergeben wäre."""
    return Counter(s.matriculation_number[-code_length:] for s in students)


def minimal_code_length(
    students: list[Student],
    room_count: int,
    candidates: tuple[int, ...] = DEFAULT_CODE_LENGTHS,
) -> int | None:
    """Bestimmt die kleinste brauchbare Stellenzahl des Anzeigecodes.

    Geprüft wird eine notwendige Bedingung: Teilen sich $m$ Studierende denselben
    Code, so müssen sie auf $m$ verschiedene Räume verteilt werden; mehr als
    ``room_count`` Mehrfachbelegungen sind daher grundsätzlich nicht auflösbar.
    Ob eine konkrete Zuweisung existiert, hängt zusätzlich von den
    Raumkapazitäten ab und zeigt sich erst beim Lauf des Algorithmus.

    Gibt ``None`` zurück, wenn keine der Kandidaten-Stellenzahlen ausreicht.
    """
    for length in sorted(candidates):
        if max(code_multiplicities(students, length).values(), default=0) <= room_count:
            return length
    return None


def find_code_collisions(students: list[Student], code_length: int) -> dict[str, list[str]]:
    """Gibt je mehrfach vergebenem Anzeigecode die betroffenen Matrikelnummern zurück."""
    by_code: dict[str, list[str]] = {}
    for student in students:
        by_code.setdefault(student.matriculation_number[-code_length:], []).append(
            student.matriculation_number
        )
    return {code: numbers for code, numbers in by_code.items() if len(numbers) > 1}


def group_sizes(students: list[Student]) -> Counter[str]:
    """Anzahl der Studierenden je Seminargruppe (nützlich für die Greedy-Sortierung)."""
    return Counter(student.seminar_group for student in students)
