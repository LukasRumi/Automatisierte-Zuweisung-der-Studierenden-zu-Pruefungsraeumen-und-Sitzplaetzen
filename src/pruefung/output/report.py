"""Maschinenlesbare Auswertung: Strafkosten, Laufzeiten und Validierungsergebnisse."""

from __future__ import annotations

import json
from pathlib import Path

from pruefung.constraints import (
    Weights,
    compactness_gap_cost,
    find_code_violations,
    find_forced_neighbor_pairs,
    find_hard_violations,
    find_room_requirement_violations,
    fragmentation_cost,
    objective,
    sorting_cost,
)
from pruefung.models import SeatingPlan, Student, Venue
from pruefung.nta import find_nta_violations


def build_report(
    *,
    algorithm: str,
    runtime_seconds: float,
    students: list[Student],
    venue: Venue,
    plan: SeatingPlan,
    weights: Weights,
    nta_rooms: list[str] | None = None,
    extra: dict | None = None,
) -> dict:
    """Baut die JSON-Struktur für den Auswertungsreport auf."""
    students_by_id = {s.matriculation_number: s for s in students}
    violations = find_hard_violations(plan, venue, students_by_id)
    code_violations = find_code_violations(plan, venue, students_by_id)
    nta_violations = find_nta_violations(plan, venue, students_by_id, nta_rooms or [])
    room_violations = find_room_requirement_violations(plan, venue, students_by_id)

    report: dict = {
        "algorithmus": algorithm,
        "laufzeit_sekunden": round(runtime_seconds, 4),
        "anzahl_studierende": len(students),
        "anzahl_sitzplaetze": len(venue.seats),
        "anzahl_reserveplaetze": len(venue.reserved),
        "anzahl_zugewiesen": len(plan.assignments),
        "anzahl_nicht_zugewiesen": len(plan.unassigned),
        "nicht_zugewiesene_matrikelnummern": list(plan.unassigned),
        "harte_verletzungen": len(violations),
        "harte_verletzungen_details": [list(pair) for pair in violations],
        # Keine Verletzung, aber eine bewusste Entscheidung der Planung, die
        # sichtbar bleiben soll: Paare derselben Seminargruppe, die laut F
        # nebeneinander sitzen.
        "vorgaben_nebeneinander": [
            list(pair) for pair in find_forced_neighbor_pairs(plan, venue, students_by_id)
        ],
        "anzeigecode_verletzungen": len(code_violations),
        "anzeigecode_verletzungen_details": [list(pair) for pair in code_violations],
        "nta_raumverletzungen": len(nta_violations),
        "nta_raumverletzungen_details": nta_violations,
        "raumvorgaben_verletzungen": len(room_violations),
        "raumvorgaben_verletzungen_details": room_violations,
        "weiche_kosten": {
            "fragmentierung_c1": fragmentation_cost(plan, venue, students_by_id),
            "sortierung_c2": sorting_cost(plan, venue, students_by_id),
            "luecken_c3": compactness_gap_cost(plan, venue),
            "gewichte": {
                "w_fragmentierung": weights.fragmentation,
                "w_sortierung": weights.sorting,
                "w_luecken": weights.gaps,
            },
            "z_gesamt": objective(plan, venue, students_by_id, weights),
        },
    }
    if extra:
        report.update(extra)
    return report


def write_report(report: dict, path: Path | str) -> Path:
    path = Path(path)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
