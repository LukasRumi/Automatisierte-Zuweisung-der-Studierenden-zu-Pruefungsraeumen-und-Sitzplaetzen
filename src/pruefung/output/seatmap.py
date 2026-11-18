"""Räumliche Darstellung eines Sitzplans.

Beide Pläne, der öffentliche Aushang wie der interne Plan für die Aufsicht,
sollen die Sitzordnung so zeigen, wie sie im Raum tatsächlich aussieht, und
dabei die Lage der Tafel erkennbar machen. Eine nach Sitzplatzbezeichnung
sortierte Tabelle leistet das nicht: Sie sagt, dass jemand auf ``C4`` sitzt,
aber nicht, wo ``C4`` liegt.

Das eingelesene Raster ist bereits die Karte und muss lediglich gefüllt
werden. Jede Rasterzelle wird auf eine feste Breite gebracht, sodass die
Spalten untereinander stehen und die Form des Raumes erhalten bleibt.

Gezeichnet wird dabei jeder Stuhl, auch der, der leer bleiben soll. Wer vor
der Karte steht, zählt Stühle und keine vergebenen Plätze. Gänge und Wände
erscheinen dagegen als Zwischenraum und bilden die Blockstruktur des Raumes
ab.

Die Tafel liegt stets vor der ersten Zeile des Rasters.
"""

from __future__ import annotations

from collections.abc import Callable

from pruefung.models import SeatingPlan, Venue
from pruefung.parsing.rooms import BLOCKED_CHAR, SEAT_CHAR

BOARD = "TAFEL"
FREE = "-"
"""Zuweisbarer, aber unbesetzter Platz."""
RESERVE = "R"
"""Platz, der als Reserve freigehalten wird."""
BLOCKED = "."
"""Stuhl, der nach der Raumvorgabe leer bleibt.

Diese Stühle stehen im Raum und sind damit Teil dessen, was ein Prüfling
abzählt. Blieben sie auf der Karte unsichtbar, zählte er die Plätze der Reihe
anders als sie dastehen und landete auf dem falschen Stuhl. Das Muster
``X.X.X`` der üblichen Bestuhlung wäre zudem nicht zu erkennen."""
EMPTY = ""
"""Zeichen ohne Stuhl: Gang und Wand."""


def _row_cells(
    room_name: str, venue: Venue, entry: Callable[[str], str]
) -> list[list[str]]:
    """Übersetzt das Raster eines Raumes in Zellen mit ihren Einträgen.

    ``entry`` liefert zu einer Sitzplatz-Kennung den darzustellenden Text.
    Die Reihenfolge der Plätze einer Zeile entspricht der Lesereihenfolge des
    Rasters, sodass sie sich den Vorkommen von ``X`` der Reihe nach zuordnen
    lassen.
    """
    pending_per_row: dict[int, list[str]] = {}
    for seat_id in venue.rooms[room_name].seat_ids:
        pending_per_row.setdefault(venue.seats[seat_id].row, []).append(seat_id)

    text_rows: list[list[str]] = []
    for index, text in enumerate(venue.rooms[room_name].grid):
        pending = list(pending_per_row.get(index, []))
        cells: list[str] = []
        for char in text:
            if char == SEAT_CHAR and pending:
                cells.append(entry(pending.pop(0)))
            elif char == BLOCKED_CHAR:
                cells.append(BLOCKED)
            else:
                cells.append(EMPTY)
        text_rows.append(cells)
    return text_rows


def seat_entry(venue: Venue, plan: SeatingPlan, text_of: Callable[[str], str]):
    """Baut die Eintragsfunktion für ``render_seat_map``.

    ``text_of`` liefert den Eintrag für einen belegten Platz anhand der
    Matrikelnummer. Unbesetzte Plätze erscheinen je nachdem als Reserve oder
    als frei.
    """

    def entry(seat_id: str) -> str:
        matriculation_number = plan.assignments.get(seat_id)
        if matriculation_number is not None:
            return text_of(matriculation_number)
        return RESERVE if seat_id in venue.reserved else FREE

    return entry


def _centered(text: str, width: int) -> str:
    """Setzt einen Eintrag mittig in seine Zelle.

    Eine Zelle steht für einen Stuhl, und der Eintrag gehört in dessen Mitte.
    Rechtsbündig gesetzt hingen die einzeichigen Markierungen am rechten
    Zellenrand und damit sichtbar neben dem Stuhl, den sie meinen. Bleibt ein
    Zeichen übrig, geht es nach links, damit ein verkürzter Anzeigecode an
    derselben Kante steht wie ein voller.
    """
    pad = width - len(text)
    if pad <= 0:
        return text
    left = (pad + 1) // 2
    return " " * left + text + " " * (pad - left)


def render_seat_map(
    room_name: str,
    venue: Venue,
    entry: Callable[[str], str],
    cell_width: int | None = None,
) -> list[str]:
    """Zeichnet den Raum als Karte, mit der Tafel am oberen Rand."""
    text_rows = _row_cells(room_name, venue, entry)
    contents = [cell for line in text_rows for cell in line if cell]
    width = cell_width or max((len(z) for z in contents), default=len(FREE))

    drawn = [
        " ".join(_centered(cell, width) for cell in line).rstrip()
        for line in text_rows
    ]
    total_width = max(
        max((len(z) for z in drawn), default=0), len(BOARD) + 4
    )
    board = f" {BOARD} ".center(total_width, "=")
    return [board, ""] + drawn
