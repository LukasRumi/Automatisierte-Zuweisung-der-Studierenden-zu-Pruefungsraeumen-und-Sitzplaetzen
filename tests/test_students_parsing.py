from pathlib import Path

from pruefung.models import ForcedAssignment
from pruefung.parsing.students import parse_students_csv

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_parses_example_csv():
    students, forced = parse_students_csv(EXAMPLES / "students.csv")
    assert len(students) == 24
    assert all(s.seminar_group for s in students)


def test_forced_assignment_pattern_is_recognized():
    students, forced = parse_students_csv(EXAMPLES / "students.csv")
    assert ForcedAssignment(matriculation_number="4500011", room="SR1", seat_label="A1") in forced


def test_plain_text_note_does_not_create_forced_assignment():
    students, forced = parse_students_csv(EXAMPLES / "students.csv")
    numbers_with_forced = {f.matriculation_number for f in forced}
    assert "4501022" not in numbers_with_forced
    note = next(s for s in students if s.matriculation_number == "4501022")
    assert note.accommodation == "Verlaengerte Bearbeitungszeit"


def test_parses_real_export_format_without_header():
    students, forced = parse_students_csv(EXAMPLES / "pruefung1" / "teilnehmer.csv")
    assert len(students) == 139
    # Erste Datenzeile: 139889040;25INB-1;A49124, 1191870767;
    assert students[0].matriculation_number == "139889040"
    assert students[0].seminar_group == "25INB-1"
    # Das dritte Feld stammt aus dem Quellsystem und erzeugt keine Zuweisung.
    assert forced == []


def test_name_is_read_from_the_real_export_format():
    students, _ = parse_students_csv(EXAMPLES / "pruefung1" / "teilnehmer.csv")
    assert students[0].name == "A49124, 1191870767"
    assert students[0].last_name == "A49124"
    # Die Liste ist je Studiengang alphabetisch nach Nachnamen sortiert.
    assert all(s.name for s in students)


def test_name_column_is_read_from_the_header_format():
    students, _ = parse_students_csv(EXAMPLES / "students.csv")
    assert students[0].name == "Albrecht, Anna"
    assert students[0].last_name == "Albrecht"


def test_nta_flag_next_to_a_name_is_still_recognized(tmp_path):
    csv_path = tmp_path / "export.csv"
    csv_path.write_text(
        "847891;25INB-1;A49124, 1191870767;\n853261;25INB-2;P148885, 192365805;NTA\n",
        encoding="utf-8",
    )
    students, _ = parse_students_csv(csv_path)
    # Der Name darf nicht als Vermerk missdeutet werden und umgekehrt.
    assert students[0].name == "A49124, 1191870767"
    assert students[0].accommodation == ""
    assert students[1].name == "P148885, 192365805"
    assert students[1].accommodation == "NTA"


def test_nta_flag_is_recognized_in_real_export_format():
    students, _ = parse_students_csv(EXAMPLES / "pruefung1" / "teilnehmer.csv")
    nta = [s.matriculation_number for s in students if s.accommodation == "NTA"]
    assert nta == ["131892650", "228617590", "106707170", "173311170"]


def test_semicolon_delimiter_wins_over_commas_inside_a_field(tmp_path):
    csv_path = tmp_path / "export.csv"
    csv_path.write_text(
        "847891;25INB-1;A49124, 1191870767;\n853261;25INB-2;P148885, 192365805;NTA\n",
        encoding="utf-8",
    )
    students, forced = parse_students_csv(csv_path)
    assert [s.matriculation_number for s in students] == ["847891", "853261"]
    assert [s.seminar_group for s in students] == ["25INB-1", "25INB-2"]
    assert students[1].accommodation == "NTA"
    assert forced == []


def test_header_is_case_insensitive(tmp_path):
    csv_path = tmp_path / "students.csv"
    csv_path.write_text(
        "Matrikelnummer;Seminargruppe;Nachteilsausgleich\n123456;INB-1;\n", encoding="utf-8"
    )
    students, forced = parse_students_csv(csv_path)
    assert len(students) == 1
    assert students[0].matriculation_number == "123456"
    assert students[0].seminar_group == "INB-1"
