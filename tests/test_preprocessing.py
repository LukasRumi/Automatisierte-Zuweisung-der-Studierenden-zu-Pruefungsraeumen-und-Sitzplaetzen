from pruefung.models import Student
from pruefung.preprocessing import (
    apply_code_length,
    code_multiplicities,
    find_code_collisions,
    minimal_code_length,
    preprocess_students,
)


def _students(*matriculation_numbers: str) -> list[Student]:
    return preprocess_students(
        [Student(matriculation_number=m, seminar_group="G1") for m in matriculation_numbers]
    )


def test_preprocess_students_sets_the_code_only_on_request():
    students = [Student(matriculation_number="1234561", seminar_group="A")]
    assert preprocess_students(students)[0].display_code == ""
    assert preprocess_students(students, code_length=3)[0].display_code == "561"
    # Original bleibt unverändert (unveränderliches Student-Objekt).
    assert students[0].display_code == ""


def test_apply_code_length_takes_the_true_trailing_digits():
    # Der Aushang zeigt die echten Endziffern, damit jeder seinen Code findet,
    # der nach dem Ende seiner Matrikelnummer sucht.
    students = apply_code_length(_students("730081"), 3)
    assert students[0].display_code == "081"
    assert apply_code_length(_students("730081"), 4)[0].display_code == "0081"


def test_code_multiplicities_counts_shared_codes():
    counts = code_multiplicities(_students("730081", "780081", "712431"), 3)
    assert counts["081"] == 2
    assert counts["431"] == 1


def test_find_code_collisions_reports_affected_matrikelnummern():
    collisions = find_code_collisions(_students("730081", "780081", "712431"), 3)
    assert collisions == {"081": ["730081", "780081"]}


def test_minimal_code_length_picks_the_smallest_workable_value():
    # Bei zwei Stellen teilen sich alle drei den Code "81", bei drei Stellen
    # sind sie mit "081", "181" und "281" eindeutig.
    students = _students("730081", "730181", "730281")
    # Bei zwei Stellen teilen sich alle drei den Code -> mehr Räume nötig als vorhanden.
    assert minimal_code_length(students, room_count=2) == 3
    # Stehen genügend Räume bereit, genügen bereits zwei Stellen.
    assert minimal_code_length(students, room_count=3) == 2


def test_minimal_code_length_tries_four_digits():
    # Erst die vierte Stelle von hinten trennt die drei: 0081, 1081, 2081.
    students = _students("730081", "731081", "732081")
    assert minimal_code_length(students, room_count=2) == 4


def test_minimal_code_length_returns_none_when_no_candidate_suffices():
    # Vier identische Endziffernfolgen, aber nur zwei Räume.
    students = _students("710081", "720081", "730081", "740081")
    assert minimal_code_length(students, room_count=2) is None
