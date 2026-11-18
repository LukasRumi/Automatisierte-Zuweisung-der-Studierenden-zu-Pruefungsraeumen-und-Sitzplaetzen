"""Kommandozeilenschnittstelle (CLI) für die Prüfungsraumzuweisung."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from pruefung.algorithms.genetic import GAConfig
from pruefung.constraints import DEFAULT_NEIGHBOR_RADIUS, Weights
from pruefung.output.assignment_sheet import (
    render_assignment_sheet,
    write_assignment_sheet,
)
from pruefung.output.overview import write_overview
from pruefung.output.plans import write_plans
from pruefung.output.report import build_report, write_report
from pruefung.parsing.students import parse_students_csv
from pruefung.pipeline import ALGORITHMS, assign
from pruefung.preprocessing import preprocess_students
from pruefung.venue import load_venue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pruefung",
        description="Automatisierte Zuweisung von Studierenden zu Prüfungsräumen und Sitzplätzen.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    assign_parser = subparsers.add_parser("assign", help="Weist Studierende Räumen und Sitzplätzen zu.")
    assign_parser.add_argument("--students", required=True, type=Path, help="CSV-Datei mit den Studierendendaten.")
    assign_parser.add_argument("--rooms", required=True, type=Path, help="Verzeichnis mit Raum-ASCII-Dateien (*.txt).")
    assign_parser.add_argument(
        "--algorithm",
        choices=ALGORITHMS,
        default="genetic",
        help="Verfahren der Sitzplatzvergabe: 'greedy' und 'first-fit' sind die beiden "
        "konstruktiven Varianten, 'genetic' der Genetische Algorithmus.",
    )
    assign_parser.add_argument("--output", required=True, type=Path, help="Ausgabeverzeichnis für Pläne und Report.")
    assign_parser.add_argument("--neighbor-radius", type=float, default=DEFAULT_NEIGHBOR_RADIUS)
    assign_parser.add_argument(
        "--reserve-seats",
        type=int,
        default=1,
        help="Plätze, die je Raum unbelegt bleiben (Ausweichsitz bei defektem Stuhl).",
    )
    assign_parser.add_argument("--w-fragmentation", type=float, default=1.0, help="Gewicht w1 für C1 (Raumaufsplitterung).")
    assign_parser.add_argument("--w-sorting", type=float, default=0.01, help="Gewicht w2 für C2 (Sortierung).")
    assign_parser.add_argument("--w-gaps", type=float, default=1.0, help="Gewicht w3 für C3 (Lücken).")
    assign_parser.add_argument("--population", type=int, default=100, help="Populationsgröße (nur GA).")
    assign_parser.add_argument("--generations", type=int, default=200, help="Maximale Generationenzahl (nur GA).")
    assign_parser.add_argument("--mutation-rate", type=float, default=0.05, help="Mutationsrate (nur GA).")
    assign_parser.add_argument("--patience", type=int, default=40, help="Abbruch bei Konvergenz nach n Generationen (nur GA).")
    assign_parser.add_argument("--seed", type=int, default=None, help="Zufalls-Seed für Reproduzierbarkeit (nur GA).")
    assign_parser.add_argument(
        "--nta-room",
        default=None,
        help="Name des Raumes für Nachteilsausgleiche (Standard: Erkennung über den Raumnamen 'nta').",
    )
    assign_parser.add_argument(
        "--room-assignment",
        choices=("free", "rules", "rules-soft"),
        default="free",
        help="Verteilung auf die Räume: 'free' optimiert ohne Rücksicht auf Erklärbarkeit, "
        "'rules' erzeugt eine vollständig als Einteilung formulierbare Zuordnung, "
        "'rules-soft' lässt darüber hinaus einzelne Ausnahmen zu, die der Aushang "
        "über ihren Anzeigecode nennt.",
    )
    assign_parser.add_argument(
        "--rule-candidates",
        type=int,
        default=24,
        help="Wie viele Einteilungsstrukturen ausgewertet werden (nur --room-assignment rules*).",
    )
    assign_parser.add_argument(
        "--max-exceptions",
        type=int,
        default=None,
        help="Obergrenze für zugelassene Ausnahmen (nur --room-assignment rules-soft).",
    )
    assign_parser.add_argument(
        "--code-digits",
        type=int,
        default=None,
        help="Stellenzahl der auf dem Aushangplan gezeigten Endziffern "
        "(Standard: kleinster brauchbarer Wert aus 2, 3 oder 4).",
    )
    assign_parser.add_argument(
        "--format",
        choices=("text", "pdf", "both"),
        default="both",
        help="Ausgabeformat der Plaene: 'pdf' ist druckfertig, 'text' maschinell "
        "weiterverarbeitbar (Standard: beides).",
    )
    assign_parser.add_argument("--quiet", action="store_true", help="Unterdrückt die Zusammenfassung auf stdout.")

    return parser


def run_assign(args: argparse.Namespace) -> int:
    students, forced = parse_students_csv(args.students)
    students = preprocess_students(students)

    venue = load_venue(
        args.rooms,
        neighbor_radius=args.neighbor_radius,
        reserve_seats=args.reserve_seats,
    )
    weights = Weights(fragmentation=args.w_fragmentation, sorting=args.w_sorting, gaps=args.w_gaps)

    ga_config = GAConfig(
        population_size=args.population,
        generations=args.generations,
        mutation_rate=args.mutation_rate,
        patience=args.patience,
        seed=args.seed,
    )

    start = time.perf_counter()
    result = assign(
        students,
        venue,
        forced,
        algorithm=args.algorithm,
        weights=weights,
        ga_config=ga_config,
        nta_room_override=args.nta_room,
        code_length=args.code_digits,
        room_assignment=args.room_assignment,
        rule_candidates=args.rule_candidates,
        max_exceptions=args.max_exceptions,
    )
    runtime = time.perf_counter() - start
    plan = result.plan
    students = result.students

    students_by_id = {s.matriculation_number: s for s in students}
    formats = ("text", "pdf") if args.format == "both" else (args.format,)
    # Die Raumzuordnung kommt vor jeden Aushangplan in den Stapel, denn sie
    # beantwortet die erste Frage eines Pruefligs, naemlich welcher Raum seiner
    # ist, und einen gemeinsamen Eingang gibt es nicht. Ohne Einteilung hat sie
    # an der Tuer nichts zu sagen und bleibt dort weg.
    sheet = render_assignment_sheet(
        venue,
        plan,
        students_by_id,
        result.metrics.get("regeln"),
        result.metrics.get("verweise_je_raum"),
    )
    write_plans(
        venue,
        plan,
        students_by_id,
        args.output,
        formats,
        result.metrics.get("regeln"),
        result.metrics.get("ausnahmen_je_raum"),
        result.metrics.get("verweise_je_raum"),
        lead=sheet.splitlines() if result.metrics.get("regeln") else None,
    )
    write_assignment_sheet(
        venue,
        plan,
        students_by_id,
        args.output,
        formats,
        result.metrics.get("regeln"),
        result.metrics.get("verweise_je_raum"),
    )
    write_overview(
        venue, plan, students, args.output, formats, result.metrics.get("regeln")
    )
    report = build_report(
        algorithm=args.algorithm,
        runtime_seconds=runtime,
        students=students,
        venue=venue,
        plan=plan,
        weights=weights,
        nta_rooms=result.nta_rooms,
        extra=result.metrics,
    )
    write_report(report, Path(args.output) / "report.json")

    if not args.quiet:
        print(f"Algorithmus: {args.algorithm}")
        print(f"Laufzeit: {runtime:.3f}s")
        print(f"Zugewiesen: {len(plan.assignments)}/{len(students)}")
        print(f"Aushangplan zeigt {result.code_length} Endziffern der Matrikelnummer")
        # E(x) misst an der guenstigsten Einteilung je Raum, der Aushang an der
        # ausgehaengten. Beide Zahlen stehen deshalb nebeneinander.
        summary = f"{result.metrics.get('ausnahmen', 0)} Ausnahmen"
        if "aushang_eintraege" in result.metrics:
            summary += f", auf den Aushängen {result.metrics['aushang_eintraege']} Einträge"
        print(f"Raumzuordnung: {args.room_assignment} ({summary})")
        for current_room, rule in sorted(result.metrics.get("regeln", {}).items()):
            print(f"   {current_room}: {rule}")
        if result.nta_rooms:
            print(
                f"NTA: {report['anzahl_nta_studierende']} Studierende in Raum "
                f"{', '.join(result.nta_rooms)}"
            )
        if plan.unassigned:
            print(f"WARNUNG: {len(plan.unassigned)} Studierende konnten keinem Platz zugewiesen werden.")
        for seat_a, seat_b in report["vorgaben_nebeneinander"]:
            print(
                f"Hinweis: {seat_a} und {seat_b} sind laut Vorgabe mit Prüflingen derselben "
                "Seminargruppe nebeneinander besetzt."
            )
        if report["harte_verletzungen"] > 0:
            print(f"WARNUNG: {report['harte_verletzungen']} harte Restriktionsverletzungen im Ergebnis!")
        if report["anzeigecode_verletzungen"] > 0:
            print(
                f"WARNUNG: {report['anzeigecode_verletzungen']} mehrfach vergebene "
                "Endziffern innerhalb eines Raumes!"
            )
        if report["nta_raumverletzungen"] > 0:
            print(f"WARNUNG: {report['nta_raumverletzungen']} Verletzungen der NTA-Raumrestriktion!")
        if report["raumvorgaben_verletzungen"] > 0:
            print(f"WARNUNG: {report['raumvorgaben_verletzungen']} verletzte Raumvorgaben!")
        if result.metrics.get("raumvorgaben"):
            print(f"Raumvorgaben: {len(result.metrics['raumvorgaben'])}")
        notes = result.metrics.get("vermerke_ohne_wirkung", {})
        if notes:
            # Ein vertippter Raumname bliebe sonst unbemerkt eine blosse Notiz.
            print(
                f"HINWEIS: {len(notes)} Vermerke ohne Wirkung (weder NTA noch "
                "Platz- oder Raumvorgabe), siehe report.json:"
            )
            for number, text in sorted(notes.items()):
                print(f"   {number}: {text}")
        print(f"Z (gewichtete weiche Kosten): {report['weiche_kosten']['z_gesamt']:.3f}")
        print(f"Ausgabe geschrieben nach: {args.output}")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Führt einen Lauf aus und meldet Eingabefehler als Text.

    Fehlerhafte Eingabedaten sind der Normalfall und kein Programmfehler. Ein
    Python-Traceback wäre für die Prüfungsorganisation unbrauchbar, deshalb
    werden die eigenen Fehlermeldungen abgefangen und als Meldung ausgegeben.
    Unerwartete Ausnahmen bleiben unangetastet, damit sie als Fehler sichtbar
    werden.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "assign":
        parser.error("Unbekannter Befehl")
        return 2
    try:
        return run_assign(args)
    except (ValueError, FileNotFoundError, UnicodeDecodeError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 2
