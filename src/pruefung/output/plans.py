"""Erzeugung der Aushangpläne für den realen Prüfungsbetrieb.

Für jeden Raum entsteht eine Karte, die auf jedem belegten Sitzplatz den
Anzeigecode zeigt, also die letzten Ziffern der Matrikelnummer. Freie Plätze
werden ausdrücklich als solche markiert, damit das Aufsichtspersonal die
Sitzordnung eindeutig kontrollieren kann.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from pruefung.models import SeatingPlan, Student, Venue, normalise_letter
from pruefung.output.pdf import NOTICE_FONT_SIZE, write_documents_pdf, write_pdf
from pruefung.output.seatmap import (
    BLOCKED,
    FREE,
    RESERVE,
    render_seat_map,
    seat_entry,
)

CELL_WIDTH = 3
"""Mindestbreite einer Zelle der Karte. Die Markierungen für frei und Reserve
umfassen ein Zeichen. Ist der Anzeigecode länger, wächst die Zelle mit, und
zwar in allen Räumen gleich, damit die Karten einheitlich aussehen."""

EMPTY_MARKER = FREE
RESERVED_MARKER = RESERVE
"""Reservierte Plätze bleiben auf dem Aushang sichtbar, sind aber als solche
gekennzeichnet: Der Plan soll die Bestuhlung vollständig abbilden, zugleich
aber erkennbar machen, welcher Platz bewusst freigehalten wurde."""


def _code_of(student: Student) -> str:
    return student.display_code or student.matriculation_number


def _cell_width(students_by_id: Mapping[str, Student]) -> int:
    longest = max((len(_code_of(s)) for s in students_by_id.values()), default=0)
    return max(CELL_WIDTH, longest)


ZAHLWORT = {2: "zweimal", 3: "dreimal", 4: "viermal"}


def _name_key(student: Student) -> str:
    """Die normierten Buchstaben des Nachnamens, Umlaute aufgelöst."""
    letters = (normalise_letter(char) for char in student.last_name)
    return "".join(letter for letter in letters if letter is not None)


def _distinguishing_prefixes(
    carriers: Sequence[tuple[Student, str]]
) -> list[tuple[str, str]] | None:
    """Kürzester Namenspräfix, der die Träger eines Codes auseinanderhält.

    Die Einteilung trennt nach dem ersten Buchstaben des Nachnamens. Liegen
    zwei Träger desselben Codes im selben Buchstabenbereich, trennt sie das
    nicht mehr. Ein Buchstabe mehr genügt dafür fast immer, und mehr als nötig
    wird nicht preisgegeben, da die Länge aufsteigend gesucht wird.

    ``None`` bedeutet, dass kein Präfix die Träger trennt, etwa bei gleichem
    Nachnamen oder fehlendem Namen. Dann bleibt nur der Verweis an die
    Aufsicht, die den Sitzplan mit Klarnamen führt.
    """
    keys: list[tuple[str, str]] = []
    for student, room in carriers:
        key = _name_key(student)
        if not key:
            return None
        keys.append((key, room))

    for length in range(1, max(len(key) for key, _ in keys) + 1):
        prefixes = [key[:length] for key, _ in keys]
        if len(set(prefixes)) == len(prefixes):
            return sorted((key[:length], room) for key, room in keys)
    return None


def split_redirects(
    room_name: str,
    venue: Venue,
    plan: SeatingPlan,
    students_by_id: Mapping[str, Student],
    redirects: Mapping[str, str] | None,
) -> tuple[
    list[tuple[str, str]],
    list[tuple[str, list[tuple[str, str]]]],
    list[tuple[str, str]],
]:
    """Ordnet die Verweise eines Raumes nach ihrer Auflösbarkeit.

    Ein Anzeigecode ist nur innerhalb eines Raumes eindeutig. Steht ein
    verwiesener Code zugleich auf der Karte dieses Raumes, gehören beide
    Einträge zu verschiedenen Personen, und der Buchstabenbereich der
    Einteilung trennt sie nicht, denn er hat beide an dieselbe Tür geschickt.

    Zurückgegeben werden drei nach Code sortierte Listen:

    * ``eindeutig``: Paare aus Code und Zielraum. Der Code kommt hier nur
      einmal vor, der Verweis ist unmissverständlich.
    * ``verfeinert``: Paare aus Code und einer Aufteilung nach Namenspräfix.
      Der Code kommt mehrfach vor, ein längerer Präfix trennt die Träger.
    * ``ungeloest``: Paare aus Code und Zielraum, bei denen auch das nicht
      gelingt. Sie gehören an die Aufsicht.

    Aushang und Raumzuordnung greifen beide hierauf zu, damit sie denselben
    Fall nie unterschiedlich darstellen.
    """
    here: dict[str, list[Student]] = {}
    for seat_id, number in plan.assignments.items():
        if venue.seats[seat_id].room != room_name or number not in students_by_id:
            continue
        student = students_by_id[number]
        here.setdefault(_code_of(student), []).append(student)

    eindeutig: list[tuple[str, str]] = []
    verfeinert: list[tuple[str, list[tuple[str, str]]]] = []
    ungeloest: list[tuple[str, str]] = []
    for number, target in (redirects or {}).items():
        if number not in students_by_id:
            continue
        student = students_by_id[number]
        code = _code_of(student)
        if code not in here:
            eindeutig.append((code, target))
            continue
        carriers = [(other, room_name) for other in here[code]]
        carriers.append((student, target))
        split = _distinguishing_prefixes(carriers)
        if split is None:
            ungeloest.append((code, target))
        else:
            verfeinert.append((code, split))
    return (
        sorted(eindeutig),
        sorted(verfeinert, key=lambda entry: entry[0]),
        sorted(ungeloest),
    )


def render_room_plan(
    room_name: str,
    venue: Venue,
    plan: SeatingPlan,
    students_by_id: dict[str, Student],
    rule: str | None = None,
    exceptions: Sequence[str] | None = None,
    redirects: Mapping[str, str] | None = None,
) -> str:
    """Erzeugt den Aushangplan eines Raumes.

    Der Plan bildet die Sitzordnung räumlich ab und markiert die Lage der
    Tafel. Eine blosse Liste von Sitzplatzbezeichnungen genügt nicht, da sie
    nicht erkennen laesst, wo ein Platz im Raum liegt.

    Liegt eine Zuweisungsregel vor, steht sie im Kopf des Plans. Erst dadurch
    erfüllt der Aushang die Anforderung einer \"möglichst klaren Zuordnung\":
    Wer vor dem Raum steht, soll ohne Suche in der Karte erkennen können, ob
    er hier richtig ist.

    ``exceptions`` nennt die Matrikelnummern derjenigen, die im Raum sitzen,
    ohne von seiner Einteilung erfasst zu sein. Sie erscheinen als Anzeigecode
    unter der Einteilung, denn eine Einteilung ohne ihre Abweichungen wäre
    nicht nur unvollständig, sondern für die Betroffenen irreführend.

    ``redirects`` nennt die Gegenrichtung, also wen die Einteilung erfasst,
    der aber in einem anderen Raum sitzt, zusammen mit dessen Namen. Diese
    Angabe steht auf dem Aushang, den die betroffene Person nach ihrem
    Anfangsbuchstaben zuerst aufsucht. Ohne sie bliebe ihr nur, die übrigen
    Räume der Reihe nach abzulaufen.

    Trägt ein verwiesener Prüfling denselben Anzeigecode wie jemand, der in
    diesem Raum sitzt, so lassen sich beide auf dem Aushang nicht trennen.
    Der Code ist nur je Raum eindeutig, und eine Ausnahme kann den Regelraum
    vom Sitzraum lösen. Statt eines Verweises erscheint dann ein Hinweis auf
    den Doppelfall, der beide Betroffenen zur Aufsicht schickt.
    """
    header = f"Aushangplan Raum {room_name}"
    lines = [header, "=" * len(header), ""]
    if rule:
        lines.append(f"Zuordnung: {rule}")
        codes = sorted(
            _code_of(students_by_id[number])
            for number in (exceptions or [])
            if number in students_by_id
        )
        if codes:
            lines.append(f"Zusätzlich in diesem Raum: {', '.join(codes)}")
        eindeutig, verfeinert, ungeloest = split_redirects(
            room_name, venue, plan, students_by_id, redirects
        )
        if eindeutig:
            verweise = ", ".join(f"{code} ({target})" for code, target in eindeutig)
            lines.append(f"Nicht in diesem Raum: {verweise}")
        for code, split in verfeinert:
            wie_oft = ZAHLWORT.get(len(split), f"{len(split)}-mal")
            lines.append(f"Code {code} kommt {wie_oft} vor:")
            for prefix, room in split:
                ziel = "hier" if room == room_name else room
                lines.append(f"    Nachname mit {prefix:<6}{ziel}")
        for code, target in ungeloest:
            lines.append(
                f"Achtung, Code {code} kommt doppelt vor: ein Prüfling sitzt in diesem "
                f"Raum, ein zweiter in {target}. Bitte vor dem Hinsetzen bei der "
                f"Aufsicht melden."
            )
        lines.append("")

    entry = seat_entry(
        venue, plan, lambda matriculation_number: _code_of(students_by_id[matriculation_number])
    )
    lines.extend(render_seat_map(room_name, venue, entry, _cell_width(students_by_id)))
    lines.append("")
    lines.append(
        f"Gezeigt sind die letzten Ziffern der Matrikelnummer. "
        f"{BLOCKED} = Stuhl bleibt leer, {FREE} = Platz nicht vergeben, "
        f"{RESERVE} = Reserve."
    )

    return "\n".join(lines) + "\n"


def write_plans(
    venue: Venue,
    plan: SeatingPlan,
    students_by_id: dict[str, Student],
    output_dir: Path | str,
    formats: Sequence[str] = ("text", "pdf"),
    rules: Mapping[str, str] | None = None,
    exceptions: Mapping[str, Sequence[str]] | None = None,
    redirects: Mapping[str, Mapping[str, str]] | None = None,
    lead: Sequence[str] | None = None,
) -> list[Path]:
    """Schreibt für jeden Raum einen Aushangplan und gibt die Pfade zurück.

    Je Raum entsteht eine eigene Datei, da die Pläne an verschiedenen Räumen
    ausgehängt werden. Das PDF legt Seitenumbrüche und Zeilenlänge fest und ist
    damit unmittelbar druckfertig, die Textfassung bleibt für die
    Weiterverarbeitung erhalten. Gesetzt wird im Querformat, da die Karte das
    Raumraster abbildet und dadurch breiter als hoch ausfällt.

    Zusätzlich entsteht ``aushaenge.pdf`` mit allem, was öffentlich hängt,
    also für jede Tür die Raumzuordnung und dahinter den Aushangplan des
    Raumes, beide ab einer eigenen Seite. Erst beides zusammen führt einen
    Prüfling zu seinem Platz, und als eine Datei ist es ein einziger
    Druckauftrag. Verteilt wird der Stapel anschließend entlang der Seiten.
    Einen gemeinsamen Eingang gibt es nicht, deshalb braucht jede Tür ihr
    eigenes Exemplar der Raumzuordnung. Die Einzeldateien bleiben daneben
    bestehen, damit sich ein beschädigter Aushang nachdrucken lässt, ohne die
    übrigen erneut auszugeben.

    ``lead`` ist das Blatt, das vor jedem Aushangplan in den Stapel kommt.
    Ohne Angabe besteht der Stapel allein aus den Aushangplänen.

    ``rules`` ordnet Raumnamen die zugehörige Zuweisungsregel in der
    aushängbaren Schreibweise zu, ``exceptions`` die Matrikelnummern der von
    ihr abweichenden Prüflinge und ``redirects`` je Raum die Prüflinge, die
    seine Einteilung nennt, obwohl sie anderswo sitzen. Ohne
    einteilungsbasierte Raumzuordnung bleiben alle drei leer und der Plankopf
    unverändert.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    alle: list[list[str]] = []
    for room_name in sorted(venue.rooms):
        content = render_room_plan(
            room_name,
            venue,
            plan,
            students_by_id,
            (rules or {}).get(room_name),
            (exceptions or {}).get(room_name),
            (redirects or {}).get(room_name),
        )
        if "text" in formats:
            path = output_dir / f"plan_{room_name}.txt"
            path.write_text(content, encoding="utf-8")
            written.append(path)
        if "pdf" in formats:
            if lead:
                alle.append(list(lead))
            alle.append(content.splitlines())
            written.append(
                write_pdf(
                    output_dir / f"plan_{room_name}.pdf",
                    content.splitlines(),
                    f"Aushangplan Raum {room_name}",
                    landscape=True,
                    size=NOTICE_FONT_SIZE,
                )
            )

    if alle:
        written.append(
            write_documents_pdf(
                output_dir / "aushaenge.pdf",
                alle,
                "Aushänge zur Prüfung",
                landscape=True,
                size=NOTICE_FONT_SIZE,
            )
        )
    return written
