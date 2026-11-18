"""Tests der Kommandozeilenschnittstelle.

Im Mittelpunkt steht das Verhalten bei fehlerhaften Eingaben. Fehlerhafte
Daten sind der Normalfall und kein Programmfehler, weshalb das Werkzeug mit
einer Meldung und einem Rueckgabewert enden muss statt mit einem Traceback.
"""

from pathlib import Path

import pytest

from pruefung.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "pruefung1"


def _argv(students, output, **extra) -> list[str]:
    argv = [
        "assign",
        "--students", str(students),
        "--rooms", str(EXAMPLES / "rooms"),
        "--output", str(output),
        "--algorithm", "first-fit",
        "--format", "text",
        "--quiet",
    ]
    for name, value in extra.items():
        argv += [f"--{name.replace('_', '-')}", str(value)]
    return argv


def test_a_successful_run_returns_zero(tmp_path):
    assert main(_argv(EXAMPLES / "teilnehmer.csv", tmp_path)) == 0
    assert (tmp_path / "report.json").exists()


def test_a_missing_file_reports_a_message(tmp_path, capsys):
    code = main(_argv(tmp_path / "gibtsnicht.csv", tmp_path / "out"))

    assert code == 2
    fehler = capsys.readouterr().err
    assert "Fehler:" in fehler
    assert "Traceback" not in fehler


def test_duplicate_matriculation_numbers_are_rejected(tmp_path, capsys):
    # Zwei Zeilen mit derselben Nummer wuerden still zu zwei Eintraegen
    # fuehren, von denen einer den anderen verdraengt. Das faellt sonst erst
    # am Pruefungstag auf.
    liste = tmp_path / "doppelt.csv"
    liste.write_text(
        "7300811;25INB-1;Albrecht, Anna;\n"
        "7300811;25INB-2;Berger, Ben;\n",
        encoding="utf-8",
    )

    code = main(_argv(liste, tmp_path / "out"))

    assert code == 2
    assert "7300811" in capsys.readouterr().err


def test_an_unusable_code_length_reports_the_conflict(tmp_path, capsys):
    # Drei Pruefline mit identischen Endziffern, aber nur ein Raum: Der
    # Anzeigecode laesst sich nicht eindeutig vergeben.
    liste = tmp_path / "codes.csv"
    liste.write_text(
        "1000001;G1;Albrecht, Anna;\n"
        "2000001;G2;Berger, Ben;\n"
        "3000001;G3;Conrad, Cem;\n",
        encoding="utf-8",
    )
    raum = tmp_path / "raeume"
    raum.mkdir()
    (raum / "R1.txt").write_text("X.X.X.X\n", encoding="utf-8")

    code = main([
        "assign",
        "--students", str(liste),
        "--rooms", str(raum),
        "--output", str(tmp_path / "out"),
        "--algorithm", "first-fit",
        "--format", "text",
        "--quiet",
    ])

    assert code == 2
    assert "Fehler:" in capsys.readouterr().err


def test_an_unknown_algorithm_is_rejected_by_the_parser(tmp_path):
    # argparse beendet den Prozess selbst, bevor die eigene Logik greift.
    with pytest.raises(SystemExit):
        main(_argv(EXAMPLES / "teilnehmer.csv", tmp_path, algorithm="zufall"))
