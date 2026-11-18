"""Erzeugung synthetischer Prüfungsinstanzen für die Evaluierung.

Die reale Instanz erlaubt belastbare Aussagen über ihre eigene Konfiguration,
nicht aber über das Verhalten der Verfahren im Allgemeinen. Um Aussagen von der
Einzelinstanz zu lösen, erzeugt dieses Modul Instanzen mit steuerbaren
Eigenschaften -- insbesondere dem Auslastungsgrad, der sich als die
maßgebliche Einflussgröße erwiesen hat.

Die Erzeugung bildet die Eigenschaften der realen Daten nach:

* **Raumlayouts** folgen dem Muster ``X.X.X.X``: In einer Sitzreihe bleibt
  jeder zweite Platz frei. Leere Reihen trennen die Sitzreihen wie in den
  realen Räumen.
* **Nachnamen** folgen der Häufigkeitsverteilung deutscher Anfangsbuchstaben.
  Eine Gleichverteilung würde die alphabetische Aufteilung unrealistisch
  begünstigen, da reale Namen sich auf wenige Buchstaben häufen.
* **Matrikelnummern** bestehen aus sechs zufälligen Ziffern und einer siebten,
  die nur 1 oder 2 lautet. Wie in der realen Liste unterscheidet die letzte
  Stelle damit wenig.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass

from pruefung.constraints import DEFAULT_NEIGHBOR_RADIUS, compute_neighbors
from pruefung.models import Student, Venue
from pruefung.parsing.rooms import parse_room_grid

# Geschätzte Häufigkeit deutscher Nachnamen-Anfangsbuchstaben in Prozent.
#
# Die Werte sind keine erhobene Statistik, sondern der realen Teilnehmerliste
# nachempfunden. Fuer den Zweck des Generators genuegt das: Maßgeblich ist
# allein, dass die Verteilung ungleich ist und sich auf wenige Buchstaben
# haeuft, da eine Gleichverteilung die alphabetische Aufteilung unrealistisch
# beguenstigen wuerde.
NAME_INITIAL_WEIGHTS: dict[str, float] = {
    "A": 2.5, "B": 9.5, "C": 2.0, "D": 3.0, "E": 2.5, "F": 4.5, "G": 5.0,
    "H": 9.5, "I": 0.5, "J": 1.5, "K": 8.5, "L": 4.5, "M": 7.5, "N": 2.5,
    "O": 1.0, "P": 3.5, "Q": 0.2, "R": 5.5, "S": 13.0, "T": 3.0, "U": 0.8,
    "V": 1.5, "W": 5.5, "X": 0.1, "Y": 0.2, "Z": 2.0,
}


@dataclass(frozen=True, slots=True)
class InstanceSpec:
    """Beschreibung einer zu erzeugenden Prüfungsinstanz."""

    students: int = 120
    groups: int = 8
    rooms: int = 3
    utilisation: float = 0.9
    """Angestrebter Anteil belegter Plätze, steuert die Knappheit der Instanz.

    Werte über 1 erzeugen eine überbestimmte Instanz mit weniger Plätzen als
    Prüflingen. Eine vollständige Zuweisung ist dann ausgeschlossen, was das
    Verhalten des Werkzeugs im Fehlerfall prüfbar macht.
    """
    nta_fraction: float = 0.03
    seed: int = 0
    irregular_rows: bool = False
    """Reihen unterschiedlicher Länge innerhalb eines Raumes, wie sie in
    Hörsälen mit ansteigender Bestuhlung auftreten."""
    with_names: bool = True
    """Ohne Namen greift die alphabetische Sortierung nicht und das Werkzeug
    muss auf die Matrikelnummer ausweichen."""


def _draw_initial(rng: random.Random) -> str:
    letters = list(NAME_INITIAL_WEIGHTS)
    initial_weights = [NAME_INITIAL_WEIGHTS[b] for b in letters]
    return rng.choices(letters, weights=initial_weights, k=1)[0]


def _make_name(rng: random.Random) -> str:
    last_name = _draw_initial(rng) + "".join(
        rng.choice(string.ascii_lowercase) for _ in range(rng.randint(3, 7))
    )
    first_name = rng.choice(string.ascii_uppercase) + "".join(
        rng.choice(string.ascii_lowercase) for _ in range(rng.randint(2, 6))
    )
    return f"{last_name}, {first_name}"


def _seat_row(seat_count: int) -> str:
    return "X" + ".X" * (seat_count - 1)


def _room_grid(seats: int, rng: random.Random, irregular: bool = False) -> list[str]:
    """Baut ein Raster im Muster ``X.X.X.X`` mit ungefähr ``seats`` Plätzen.

    Zwischen je zwei Sitzreihen liegt eine leere Reihe, wie in den realen
    Räumen. Die Reihenbreite schwankt leicht, damit die Instanzen nicht
    künstlich gleichförmig ausfallen.

    Mit ``irregular`` schwankt sie zusätzlich von Reihe zu Reihe. Das bildet
    Hörsäle nach, deren Reihen nach hinten breiter werden, und prüft, ob die
    Verarbeitung ungleich lange Zeilen verträgt.
    """
    seats_per_row = max(4, rng.randint(6, 9))
    rows = max(1, -(-seats // seats_per_row))
    widest = "." * len(_seat_row(seats_per_row + (3 if irregular else 0)))

    grid: list[str] = []
    remaining = seats
    for index in range(rows):
        if irregular:
            width = max(3, seats_per_row + rng.randint(-2, 3))
        else:
            width = seats_per_row
        grid.append(_seat_row(width))
        remaining -= width
        if index % 2 == 1 and index < rows - 1:
            grid.append(widest)

    # Bei schwankender Breite kann das Raster zu klein ausfallen; fehlende
    # Plätze kommen als zusätzliche Reihe hinzu.
    if remaining > 0:
        grid.append(_seat_row(remaining))
    return grid


def generate_instance(spec: InstanceSpec) -> tuple[list[Student], Venue, list[str]]:
    """Erzeugt Studierende und Prüfungsort zu einer Beschreibung.

    Zurückgegeben werden die Studierenden, der Prüfungsort und die Namen der
    Räume, die für Nachteilsausgleiche vorgesehen sind.
    """
    if spec.utilisation <= 0:
        raise ValueError("Der Auslastungsgrad muss größer als 0 sein.")
    if spec.rooms < 1 or spec.groups < 1 or spec.students < 1:
        raise ValueError("Räume, Gruppen und Studierende müssen positiv sein.")

    rng = random.Random(spec.seed)

    nta_count = round(spec.students * spec.nta_fraction)
    regular = spec.students - nta_count

    group_names = [f"{25 - i % 3}GRP-{i // 3 + 1}" for i in range(spec.groups)]
    student_list: list[Student] = []
    bases = rng.sample(range(100000, 999999), spec.students)
    for index, base in enumerate(bases):
        indicator = rng.choice("12")
        student_list.append(
            Student(
                matriculation_number=f"{base}{indicator}",
                seminar_group=group_names[index % spec.groups],
                name=_make_name(rng) if spec.with_names else "",
                accommodation="NTA" if index < nta_count else "",
            )
        )
    rng.shuffle(student_list)

    # Reguläre Räume so dimensionieren, dass der Auslastungsgrad erreicht wird.
    total_seats = round(regular / spec.utilisation)
    if spec.utilisation <= 1:
        # Rundung darf die Instanz nicht unbeabsichtigt überbestimmt machen.
        total_seats = max(regular, total_seats)
    total_seats = max(spec.rooms, total_seats)
    per_room = [total_seats // spec.rooms] * spec.rooms
    for i in range(total_seats - sum(per_room)):
        per_room[i % spec.rooms] += 1

    rooms, seats = {}, {}
    for number, size in enumerate(per_room, start=1):
        name = f"R{number}"
        current_room, room_seats = parse_room_grid(
            name, _room_grid(size, rng, spec.irregular_rows)
        )
        rooms[name] = current_room
        seats.update(room_seats)

    nta_rooms: list[str] = []
    if nta_count:
        # Der NTA-Raum erhält etwas Reserve, damit die Trennung der
        # Seminargruppen auch dort erfüllbar bleibt.
        current_room, room_seats = parse_room_grid("NTA", _room_grid(max(4, nta_count * 3), rng))
        rooms["NTA"] = current_room
        seats.update(room_seats)
        nta_rooms.append("NTA")

    venue = Venue(
        rooms=rooms,
        seats=seats,
        neighbors=compute_neighbors(seats, radius=DEFAULT_NEIGHBOR_RADIUS),
    )
    return student_list, venue, nta_rooms
