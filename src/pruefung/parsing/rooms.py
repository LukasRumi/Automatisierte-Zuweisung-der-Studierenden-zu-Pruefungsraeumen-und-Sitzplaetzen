"""Einlesen von Prüfungsräumen aus 2D-ASCII-Rastern.

Zeichenkodierung (siehe Kapitel 4 der Arbeit):

* ``X``           ein valider, zuweisbarer Sitzplatz.
* ``.``           ein physischer Platz, der zwingend leer bleiben muss.
* ``_`` / " "     Gangfläche bzw. Bereich ohne Tische.
* ``<``           ein Leerraum mit exakt halber Sitzbreite.

Die Längeneinheit des internen Koordinatensystems ist eine Sitzbreite: Ein
reguläres Zeichen ist ``FULL_WIDTH`` = 1 breit, das Zeichen ``<`` entsprechend
``HALF_WIDTH`` = 0.5. Eine Zeile entspricht einer Sitzreihe und ist
``ROW_HEIGHT`` = 1 hoch. Die x-Koordinate eines Sitzplatzes ist die Mitte
seiner Zellenspanne innerhalb der Zeile.

Eine Abstandsangabe lässt sich damit unmittelbar lesen: Abstand 1 bedeutet
"einen Platz entfernt". Halbe Sitzbreiten sind der Grund, weshalb die
Koordinaten als Fließkommazahlen und nicht als Spalten-/Reihenindizes geführt
werden -- im Raum TR129 etwa ist der hintere Sitzblock um eine halbe Sitzbreite
gegen den vorderen versetzt.

``ROW_HEIGHT`` = 1 setzt den Reihenabstand bewusst mit der Sitzbreite gleich.
Die ASCII-Notation trägt keine metrische Information, und Hörsäle
unterscheiden sich in ihrer Bestuhlung zu stark für einen allgemeingültigen
Wert. Der Fehler wirkt konservativ: Ist der echte Reihenabstand größer als die
Sitzbreite (der Regelfall), sind Plätze anderer Reihen real weiter entfernt als
angenommen, die Trennungs-Restriktion wirkt also strenger statt nachlässiger.
"""

from __future__ import annotations

from pathlib import Path

from pruefung.models import Room, Seat

SEAT_CHAR = "X"
BLOCKED_CHAR = "."
HALF_WIDTH_CHAR = "<"

FULL_WIDTH = 1.0
HALF_WIDTH = 0.5
ROW_HEIGHT = 1.0


def _char_width(ch: str) -> float:
    return HALF_WIDTH if ch == HALF_WIDTH_CHAR else FULL_WIDTH


def _row_label(row_index: int) -> str:
    """Wandelt einen 0-basierten Zeilenindex in eine Buchstabenbezeichnung um (0->A, 25->Z, 26->AA, ...)."""
    n = row_index + 1
    letters = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def parse_room_grid(name: str, grid: list[str]) -> tuple[Room, dict[str, Seat]]:
    """Erzeugt aus einem bereits eingelesenen Raster ein ``Room``- und ``Seat``-Modell."""
    seats: dict[str, Seat] = {}
    seat_ids: list[str] = []

    for row_index, line in enumerate(grid):
        x = 0.0
        seats_in_row = 0
        for ch in line:
            width = _char_width(ch)
            if ch == SEAT_CHAR:
                seats_in_row += 1
                label = f"{_row_label(row_index)}{seats_in_row}"
                seat_id = f"{name}:{label}"
                seat = Seat(
                    id=seat_id,
                    room=name,
                    label=label,
                    row=row_index,
                    col=seats_in_row,
                    x=x + width / 2,
                    y=row_index * ROW_HEIGHT,
                )
                seats[seat_id] = seat
                seat_ids.append(seat_id)
            x += width

    room = Room(name=name, grid=grid, seat_ids=seat_ids)
    return room, seats


def parse_room_file(path: Path | str) -> tuple[Room, dict[str, Seat]]:
    """Liest eine Raum-Textdatei ein. Der Dateiname (ohne Endung) dient als Raumname."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    # Nachgestellte Leerzeilen (z. B. abschließender Zeilenumbruch) tragen keine Information.
    while lines and lines[-1].strip() == "":
        lines.pop()
    return parse_room_grid(path.stem, lines)


def parse_rooms_dir(directory: Path | str) -> tuple[dict[str, Room], dict[str, Seat]]:
    """Liest alle ``*.txt``-Dateien eines Verzeichnisses als Prüfungsräume ein."""
    directory = Path(directory)
    rooms: dict[str, Room] = {}
    seats: dict[str, Seat] = {}
    for path in sorted(directory.glob("*.txt")):
        room, room_seats = parse_room_file(path)
        if room.name in rooms:
            raise ValueError(f"Raumname '{room.name}' ist nicht eindeutig (Datei: {path}).")
        rooms[room.name] = room
        seats.update(room_seats)
    if not rooms:
        raise ValueError(f"Keine Raum-Dateien (*.txt) in '{directory}' gefunden.")
    return rooms, seats
