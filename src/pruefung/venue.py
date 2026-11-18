"""Zusammenbau des ``Venue``-Modells aus den geparsten Rauminformationen."""

from __future__ import annotations

from pathlib import Path

from pruefung.constraints import DEFAULT_NEIGHBOR_RADIUS, compute_neighbors
from pruefung.models import Room, Venue
from pruefung.parsing.rooms import parse_rooms_dir


def load_venue(
    rooms_dir: Path | str,
    neighbor_radius: float = DEFAULT_NEIGHBOR_RADIUS,
    reserve_seats: int = 0,
) -> Venue:
    """Liest alle Raumdateien eines Verzeichnisses ein und berechnet die Nachbarschaften N_p."""
    rooms, seats = parse_rooms_dir(rooms_dir)
    neighbors = compute_neighbors(seats, radius=neighbor_radius)
    return Venue(
        rooms=rooms,
        seats=seats,
        neighbors=neighbors,
        reserved=_reserved_seats(rooms, reserve_seats),
    )


def _reserved_seats(rooms: dict[str, Room], count: int) -> frozenset[str]:
    """Bestimmt je Raum die Plätze, die als Reserve freibleiben.

    In der Praxis soll in jedem Prüfungsraum ein bis zwei Plätze unbelegt
    bleiben, damit bei einem defekten Stuhl kurzfristig ausgewichen werden kann.
    Die Plätze bleiben Teil des Raumes und erscheinen weiterhin auf dem
    Aushangplan -- dieser soll die Bestuhlung vollständig abbilden --, stehen
    der Zuweisung aber nicht zur Verfügung. Freigehalten werden die hintersten
    Plätze, damit die Reserve die Kompaktheit der Belegung nicht zerreißt.
    """
    if count <= 0:
        return frozenset()
    return frozenset(
        seat_id
        for room in rooms.values()
        for seat_id in room.seat_ids[max(0, len(room.seat_ids) - count) :]
    )
