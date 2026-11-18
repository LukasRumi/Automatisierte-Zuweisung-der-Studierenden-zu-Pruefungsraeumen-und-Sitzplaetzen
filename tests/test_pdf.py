import pytest

from pruefung.output.pdf import (
    LINES_PER_PAGE,
    chars_per_line,
    paginate,
    render_pdf,
    wrap_lines,
    write_pdf,
)


def test_rendered_file_is_a_well_formed_pdf():
    data = render_pdf([["Aushangplan Raum TRA140", "A1   008"]])
    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")
    # Die Querverweistabelle und der Trailer müssen vorhanden sein.
    assert b"\nxref\n" in data
    assert b"trailer" in data
    assert b"startxref" in data


def test_startxref_points_at_the_cross_reference_table():
    data = render_pdf([["Zeile"]])
    position = int(data.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
    assert data[position : position + 4] == b"xref"


def test_page_count_matches_the_pages_handed_in():
    data = render_pdf([["a"], ["b"], ["c"]])
    assert b"/Count 3" in data
    assert data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") == 3


def test_paginate_splits_long_documents():
    text_rows = [f"Zeile {i}" for i in range(LINES_PER_PAGE * 2 + 5)]
    page_lines = paginate(text_rows)
    assert len(page_lines) == 3
    assert len(page_lines[0]) == LINES_PER_PAGE
    assert sum(len(s) for s in page_lines) == len(text_rows)


def test_paginate_of_nothing_yields_one_empty_page():
    assert paginate([]) == [[]]


def test_parentheses_and_backslashes_are_escaped():
    # Unmaskiert würden diese Zeichen den PDF-String vorzeitig beenden.
    data = render_pdf([[r"Gang (links) \ rechts"]])
    assert rb"\(links\)" in data
    assert rb"\\ rechts" in data


def test_umlauts_survive_as_winansi():
    data = render_pdf([["Prüfungsräume ÄÖÜ ß"]])
    assert b"/Encoding /WinAnsiEncoding" in data
    assert "Prüfungsräume ÄÖÜ ß".encode("cp1252") in data


def test_characters_outside_winansi_do_not_break_the_file():
    data = render_pdf([["Zeichen: 中文"]])
    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")


def test_write_pdf_creates_the_file(tmp_path):
    path = write_pdf(tmp_path / "unter" / "plan.pdf", ["Zeile eins", "Zeile zwei"], "Titel")
    assert path.exists()
    assert path.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("text_rows", [[], ["nur eine Zeile"]])
def test_edge_cases_produce_valid_files(tmp_path, text_rows):
    path = write_pdf(tmp_path / "x.pdf", text_rows)
    assert path.read_bytes().rstrip().endswith(b"%%EOF")


def test_short_lines_are_left_alone():
    rows = ["kurz", "auch kurz"]
    assert wrap_lines(rows, 20) == rows


def test_long_lines_are_wrapped_instead_of_overflowing():
    # Ohne Umbruch liefe ein breiter Raum rechts aus dem Blatt, ohne dass ein
    # Fehler auftraete. Die fehlenden Plaetze fielen erst am Pruefungstag auf.
    wrapped = wrap_lines(["A" * 25], 10)
    assert len(wrapped) == 3
    assert all(len(line) <= 10 for line in wrapped)
    assert "".join(line.lstrip() for line in wrapped) == "A" * 25


def test_wrapped_continuations_are_indented():
    wrapped = wrap_lines(["X" * 15], 10)
    assert wrapped[0] == "X" * 10
    assert wrapped[1].startswith("  ")


def test_wrapping_breaks_at_spaces_and_not_inside_words():
    # Ein harter Schnitt an der Spalte erzeugte "Nachn amens".
    wrapped = wrap_lines(["Es gilt der Anfangsbuchstabe Ihres Nachnamens."], 30)
    assert all(len(line) <= 30 for line in wrapped)
    assert "Nachnamens." in " ".join(line.strip() for line in wrapped)
    assert not any(line.endswith("Nachn") for line in wrapped)


def test_wrapping_keeps_display_codes_whole():
    # Auf der Sitzkarte darf ein Code nicht in zwei Zeilen zerfallen.
    row = " ".join(f"{i:03d}" for i in range(12))
    wrapped = wrap_lines([row], 20)
    codes = " ".join(line.strip() for line in wrapped).split()
    assert codes == row.split()


def test_a_word_longer_than_the_width_is_still_cut():
    # Ohne Leerzeichen bleibt nur der harte Schnitt, sonst liefe die Zeile
    # weiterhin ueber den Rand.
    wrapped = wrap_lines(["A" * 25], 10)
    assert all(len(line) <= 10 for line in wrapped)
    assert "".join(line.lstrip() for line in wrapped) == "A" * 25


def test_a_wide_room_plan_fits_on_the_page(tmp_path):
    # Breiter als FE006, also der Fall, der vorher ueberlief.
    width = chars_per_line(landscape=True, size=14)
    row = " ".join(f"{i:03d}" for i in range(40))
    assert len(row) > width
    path = write_pdf(tmp_path / "breit.pdf", [row], landscape=True, size=14)
    assert path.read_bytes().startswith(b"%PDF")
    assert all(len(line) <= width for line in wrap_lines([row], width))


def test_the_title_lands_in_the_info_dictionary():
    # Im Trailer hat /Title keine Bedeutung und wird von Betrachtern ignoriert.
    data = render_pdf([["Zeile"]], title="Aushangplan Raum TR129")
    assert b"/Info " in data
    assert b"<< /Title (Aushangplan Raum TR129) >>" in data
