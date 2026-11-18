"""Erzeugung druckfertiger PDF-Dateien ohne externe Abhängigkeiten.

Die Aushangpläne sollen am Prüfungstag ausgedruckt und aufgehängt werden. Reine
Textdateien eignen sich dafür nur bedingt, da Seitenumbrüche und Zeilenlänge vom
Druckprogramm abhängen. PDF legt beides fest.

Üblicherweise greift man dafür zu einer Bibliothek. Das widerspräche jedoch der
in Abschnitt 5.1 begründeten Entscheidung, ohne externe Laufzeitabhängigkeiten
auszukommen. Für den hier benötigten Umfang ist das auch nicht nötig: Die Pläne
bestehen ausschließlich aus Zeilen fester Breite, und PDF kennt mit Courier eine
der vierzehn Standardschriften, die kein Betrachter einbetten muss. Der erzeugte
Dateiaufbau beschränkt sich damit auf Katalog, Seitenbaum, Schrift und je einen
Textstrom pro Seite.

Die Zeichenkodierung ist ``WinAnsiEncoding``, womit deutsche Umlaute unmittelbar
darstellbar sind.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

FONT_SIZE = 10
NOTICE_FONT_SIZE = 14
"""Sitzpläne werden an die Tür gehängt und aus einigen Schritten Entfernung
gelesen. Sie erhalten daher eine größere Schrift als die Listen, die man in
der Hand hält."""

A4_SHORT = 595  # A4 in PDF-Punkten
A4_LONG = 842
MARGIN = 50
LINE_SPACING = 12

PAGE_WIDTH = A4_SHORT
PAGE_HEIGHT = A4_LONG
LINES_PER_PAGE = (A4_LONG - 2 * MARGIN) // LINE_SPACING


def line_spacing(size: int = FONT_SIZE) -> int:
    """Zeilenabstand zu einer Schriftgröße."""
    return int(size * 1.2)


def char_width(size: int = FONT_SIZE) -> float:
    """Courier ist dicktengleich, ein Zeichen ist 0,6 em breit."""
    return 0.6 * size


def page_size(landscape: bool = False) -> tuple[int, int]:
    """Breite und Höhe der Seite in PDF-Punkten.

    Sitzpläne bilden das Raumraster ab und werden dadurch breiter als hoch.
    Querformat ist für sie die passende Ausrichtung.
    """
    return (A4_LONG, A4_SHORT) if landscape else (A4_SHORT, A4_LONG)


def page_line_count(landscape: bool = False, size: int = FONT_SIZE) -> int:
    """Wie viele Textzeilen auf eine Seite passen."""
    _, height = page_size(landscape)
    return int((height - 2 * MARGIN) // line_spacing(size))


def chars_per_line(landscape: bool = False, size: int = FONT_SIZE) -> int:
    """Wie viele Zeichen in eine Zeile passen, ohne über den Rand zu laufen."""
    width, _ = page_size(landscape)
    return int((width - 2 * MARGIN) // char_width(size))


def wrap_lines(lines: list[str], width: int) -> list[str]:
    """Bricht zu lange Zeilen um, statt sie über den Rand laufen zu lassen.

    Ohne diesen Umbruch würden Räume, deren Raster breiter ist als die
    Seitenbreite, auf dem Aushang rechts abgeschnitten. Der Verlust fiele erst
    am Prüfungstag auf, und zwar genau den Prüflingen, deren Platz fehlt.
    Umbrochene Fortsetzungen werden eingerückt, damit sie als solche erkennbar
    bleiben.
    """
    if width <= 3:
        return list(lines)
    result: list[str] = []
    for line in lines:
        head, rest = _split_at(line, width)
        result.append(head)
        while rest:
            head, rest = _split_at(rest, width - 2)
            result.append("  " + head)
    return result


def _split_at(text: str, width: int) -> tuple[str, str]:
    """Trennt eine Zeile nach dem letzten Leerzeichen, das noch hineinpasst.

    Ein harter Schnitt an der Spalte zerreißt Wörter (\"Nachn amens\") und auf
    einer Sitzkarte auch Anzeigecodes. Gibt es im passenden Bereich kein
    Leerzeichen, bleibt nur der harte Schnitt.
    """
    if len(text) <= width:
        return text, ""
    cut = text.rfind(" ", 0, width + 1)
    if cut <= 0:
        return text[:width], text[width:]
    return text[:cut].rstrip(), text[cut + 1 :]


def paginate(lines: list[str], lines_per_page: int = LINES_PER_PAGE) -> list[list[str]]:
    """Teilt Zeilen in Seiten auf. Leere Eingabe ergibt eine leere Seite."""
    if not lines:
        return [[]]
    return [lines[i : i + lines_per_page] for i in range(0, len(lines), lines_per_page)]


def _escape(text: str) -> bytes:
    """Kodiert eine Zeile als PDF-Literalstring.

    Klammern und Rückstriche haben in PDF-Strings syntaktische Bedeutung und
    müssen maskiert werden. Zeichen außerhalb von WinAnsi werden ersetzt, damit
    die Datei in jedem Fall wohlgeformt bleibt.
    """
    raw = text.encode("cp1252", errors="replace")
    for char, fallback in ((b"\\", b"\\\\"), (b"(", b"\\("), (b")", b"\\)")):
        raw = raw.replace(char, fallback)
    return raw


def _content_stream(
    lines: list[str], height: int = PAGE_HEIGHT, size: int = FONT_SIZE
) -> bytes:
    """Baut den Textstrom einer Seite."""
    parts = [
        b"BT",
        f"/F1 {size} Tf".encode("ascii"),
        f"{line_spacing(size)} TL".encode("ascii"),
        f"{MARGIN} {height - MARGIN - size} Td".encode("ascii"),
    ]
    for index, line in enumerate(lines):
        if index:
            parts.append(b"T*")
        parts.append(b"(" + _escape(line) + b") Tj")
    parts.append(b"ET")
    return b"\n".join(parts)


def render_pdf(
    pages: list[list[str]],
    title: str = "",
    landscape: bool = False,
    size: int = FONT_SIZE,
) -> bytes:
    """Erzeugt ein PDF aus Seiten von Textzeilen."""
    if not pages:
        pages = [[]]
    width, height = page_size(landscape)

    objects: list[bytes] = []

    def add_entry(content: bytes) -> int:
        objects.append(content)
        return len(objects)  # Objektnummern beginnen bei 1

    # Nummern vorab festlegen: 1 Katalog, 2 Seitenbaum, 3 Schrift,
    # danach je Seite ein Seiten- und ein Inhaltsobjekt.
    catalog_no, page_tree_no, font_no = 1, 2, 3
    first_page_no = 4
    page_nos = [first_page_no + 2 * i for i in range(len(pages))]

    add_entry(f"<< /Type /Catalog /Pages {page_tree_no} 0 R >>".encode("ascii"))
    kids = " ".join(f"{obj_no} 0 R" for obj_no in page_nos)
    add_entry(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii")
    )
    add_entry(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
        b"/Encoding /WinAnsiEncoding >>"
    )

    for page_no, text_rows in zip(page_nos, pages):
        content_no = page_no + 1
        add_entry(
            (
                f"<< /Type /Page /Parent {page_tree_no} 0 R "
                f"/MediaBox [0 0 {width} {height}] "
                f"/Resources << /Font << /F1 {font_no} 0 R >> >> "
                f"/Contents {content_no} 0 R >>"
            ).encode("ascii")
        )
        stream = _content_stream(text_rows, height, size)
        add_entry(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )

    # Der Titel gehört nach ISO 32000 in ein eigenes Dokumentinformations-
    # Wörterbuch, auf das der Trailer über /Info verweist. Im Trailer selbst
    # hat /Title keine Bedeutung und wird von Betrachtern ignoriert.
    info_no = add_entry(
        b"<< /Title (" + _escape(title) + b") >>"
    ) if title else None

    # Datei zusammensetzen und dabei die Byte-Positionen für die xref-Tabelle merken.
    pdf_bytes = bytearray(b"%PDF-1.4\n")
    positions: list[int] = []
    for number, content in enumerate(objects, start=1):
        positions.append(len(pdf_bytes))
        pdf_bytes += f"{number} 0 obj\n".encode("ascii") + content + b"\nendobj\n"

    xref_start = len(pdf_bytes)
    pdf_bytes += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    pdf_bytes += b"0000000000 65535 f \n"
    for position in positions:
        pdf_bytes += f"{position:010d} 00000 n \n".encode("ascii")

    trailer = f"<< /Size {len(objects) + 1} /Root {catalog_no} 0 R"
    if info_no is not None:
        trailer += f" /Info {info_no} 0 R"
    trailer += " >>"
    pdf_bytes += b"trailer\n" + trailer.encode("cp1252", errors="replace")
    pdf_bytes += f"\nstartxref\n{xref_start}\n%%EOF\n".encode("ascii")
    return bytes(pdf_bytes)


def write_pdf(
    path: Path | str,
    lines: list[str],
    title: str = "",
    landscape: bool = False,
    size: int = FONT_SIZE,
) -> Path:
    """Schreibt Textzeilen als druckfertiges PDF.

    Zu lange Zeilen werden umbrochen, zu viele auf Folgeseiten verteilt. Der
    Inhalt geht damit in keiner Richtung über den Seitenrand hinaus.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wrapped = wrap_lines(lines, chars_per_line(landscape, size))
    page_lines = paginate(wrapped, page_line_count(landscape, size))
    path.write_bytes(render_pdf(page_lines, title, landscape, size))
    return path


def write_documents_pdf(
    path: Path | str,
    documents: Sequence[Sequence[str]],
    title: str = "",
    landscape: bool = False,
    size: int = FONT_SIZE,
) -> Path:
    """Schreibt mehrere Dokumente in eine Datei, jedes ab einer neuen Seite.

    ``write_pdf`` paginiert fortlaufend und ließe damit das Ende eines
    Aushangs und den Anfang des nächsten auf derselben Seite stehen. Ein
    Stapel, der auf verschiedene Türen verteilt wird, muss sich aber entlang
    der Seiten trennen lassen.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    width = chars_per_line(landscape, size)
    height = page_line_count(landscape, size)
    pages: list[list[str]] = []
    for document in documents:
        pages.extend(paginate(wrap_lines(list(document), width), height))
    path.write_bytes(render_pdf(pages or [[]], title, landscape, size))
    return path
