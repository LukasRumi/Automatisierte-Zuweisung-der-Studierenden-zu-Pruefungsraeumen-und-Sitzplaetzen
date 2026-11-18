"""Die öffentliche Raumzuordnung, der erste Zettel vor der Prüfung.

Der Aushangplan aus ``pruefung.output.plans`` hängt an der Tür und nennt nur
die Einteilung seines eigenen Raumes. Wer vor einer Tür steht, deren
Einteilung ihn nicht erfasst, erfährt daraus nicht, wohin er gehen muss.
Einen gemeinsamen Eingang gibt es nicht, da Prüfungsräume an einer Hochschule
in verschiedenen Gebäuden liegen.

Diese Ausgabe schließt die Lücke. Sie hängt an jeder Tür neben dem
Aushangplan, lässt sich zusätzlich mit der Einladung verschicken und nennt die
Einteilungen aller Räume samt der Abweichungen. Wer sie schon vorher erhalten
hat, geht genau einen Weg.

Veröffentlicht werden dabei nur Angaben, die ohnehin an den Türen hängen,
nämlich Raumnamen, Buchstabenbereiche und Anzeigecodes. Klarnamen und
vollständige Matrikelnummern erscheinen nicht.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from pruefung.models import SeatingPlan, Student, Venue
from pruefung.output.pdf import NOTICE_FONT_SIZE, write_pdf
from pruefung.output.plans import ZAHLWORT, split_redirects

TITLE = "Raumzuordnung zur Prüfung"


def render_assignment_sheet(
    venue: Venue,
    plan: SeatingPlan,
    students_by_id: Mapping[str, Student],
    rules: Mapping[str, str] | None = None,
    redirects: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """Erzeugt die Raumzuordnung als Text.

    Der Aufbau folgt der Reihenfolge, in der ein Prüfling liest. Zuerst die
    Anweisung, dann die Buchstabenbereiche je Raum, dann die Codes mit eigener
    Angabe.

    Diese letzte Liste führt alle Sonderfälle zusammen, statt sie auf mehrere
    Abschnitte zu verteilen. Wer seinen Code in einer ersten Liste nicht
    findet, folgt dem Buchstaben und liest eine zweite gar nicht mehr. Eine
    einzige, nach Code sortierte Liste gibt es dagegen nur einmal
    nachzuschlagen.

    Aufgenommen werden drei Arten von Einträgen. Abweichende Prüflinge
    erhalten den Raum, in dem sie sitzen. Tragen zwei denselben Code und
    schickt die Einteilung beide an dieselbe Tür, so entscheidet ein Buchstabe
    mehr vom Anfang des Nachnamens, und beide Träger stehen mit ihrem Präfix
    in der Liste. Gelingt auch das nicht, etwa bei gleichem Nachnamen, bleibt
    der Verweis an die Aufsicht, deren Sitzplan die Klarnamen führt.
    """
    rules = rules or {}
    lines = [TITLE, "=" * len(TITLE), ""]

    if not rules:
        lines.append(
            "Für diese Prüfung wurde keine Einteilung nach Anfangsbuchstaben gebildet."
        )
        lines.append("Die Raumzuordnung entnehmen Sie bitte den Aushängen an den Türen.")
        return "\n".join(lines) + "\n"

    eindeutig: list[tuple[str, str]] = []
    verfeinert: list[tuple[str, list[tuple[str, str]]]] = []
    doppeldeutig: list[tuple[str, str, str]] = []
    for room_name in sorted(rules):
        klar, fein, unklar = split_redirects(
            room_name, venue, plan, students_by_id, (redirects or {}).get(room_name)
        )
        eindeutig.extend(klar)
        verfeinert.extend(fein)
        doppeldeutig.extend((code, room_name, target) for code, target in unklar)

    # Alle Codes, die eine eigene Angabe brauchen, stehen in einer einzigen
    # Liste. Zwei getrennte Abschnitte hiessen, dass wer seinen Code im ersten
    # nicht findet, dem Buchstaben folgt und den zweiten nie liest.
    rows: list[tuple[str, str, str]] = []
    rows.extend((code, "", target) for code, target in eindeutig)
    for code, split in verfeinert:
        rows.extend((code, f"Nachname mit {prefix}", room) for prefix, room in split)
    rows.extend(
        (code, "bei der Aufsicht melden", f"{room_name} oder {target}")
        for code, room_name, target in doppeldeutig
    )
    rows.sort()

    # Der Hinweis darf nur auf Abschnitte verweisen, die es auch gibt.
    if rows:
        lines.append("Suchen Sie Ihren Anzeigecode in der Liste unten.")
        lines.append("Steht er nicht dort, gilt Ihr Anfangsbuchstabe.")
    else:
        lines.append("Es gilt der Anfangsbuchstabe Ihres Nachnamens.")
    lines.append("")

    # Sortiert wird nach der Einteilung und nicht nach dem Raumnamen, denn
    # gesucht wird der eigene Anfangsbuchstabe und nicht der Raum.
    breite = max((len(rule) for rule in rules.values()), default=0) + 4
    for room_name in sorted(rules, key=lambda name: (rules[name], name)):
        lines.append(f"{rules[room_name]:<{breite}}{room_name}")
    lines.append("")

    if rows:
        titel = "Codes mit eigener Angabe"
        lines.append(titel)
        lines.append("-" * len(titel))
        lines.append("")
        code_breite = max(len(code) for code, _, _ in rows) + 2
        zusatz_breite = max(len(zusatz) for _, zusatz, _ in rows)
        if zusatz_breite:
            zusatz_breite += 2
        for code, zusatz, room_name in rows:
            lines.append(
                f"{code:<{code_breite}}{zusatz:<{zusatz_breite}}{room_name}"
            )
        lines.append("")

    lines.append("Gezeigt sind die letzten Ziffern der Matrikelnummer.")
    return "\n".join(lines) + "\n"


def write_assignment_sheet(
    venue: Venue,
    plan: SeatingPlan,
    students_by_id: Mapping[str, Student],
    output_dir: Path | str,
    formats: Sequence[str] = ("text", "pdf"),
    rules: Mapping[str, str] | None = None,
    redirects: Mapping[str, Mapping[str, str]] | None = None,
) -> list[Path]:
    """Schreibt die Raumzuordnung und gibt die erzeugten Pfade zurück.

    Gesetzt wird im Hochformat und in der Schriftgröße des Aushangs, da der
    Zettel wie dieser aus einigen Schritten Entfernung gelesen wird.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    content = render_assignment_sheet(venue, plan, students_by_id, rules, redirects)
    written: list[Path] = []
    if "text" in formats:
        path = output_dir / "raumzuordnung.txt"
        path.write_text(content, encoding="utf-8")
        written.append(path)
    if "pdf" in formats:
        written.append(
            write_pdf(
                output_dir / "raumzuordnung.pdf",
                content.splitlines(),
                TITLE,
                size=NOTICE_FONT_SIZE,
            )
        )
    return written
