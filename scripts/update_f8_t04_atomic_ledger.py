#!/usr/bin/env python3
"""Record incremental F8-T04 implementation and verification evidence."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = (
    ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
    / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
)
MATCHES = list(LEDGER_DIR.glob("F8-T04_*.json"))
if len(MATCHES) != 1:
    raise RuntimeError(f"Expected one F8-T04 ledger, found {len(MATCHES)}")
LEDGER = MATCHES[0]


BATCHES = {
    "backend-projection": {
        "atoms": ["G19-R01", "G19-R02", "G19-R03", "G19-R04", "G19-R05", "G19-R07", "G19-R08"],
        "files": ["app/profile_summary.py", "app/dashboard_summary.py", "app/m5_api.py"],
        "result": (
            "The owner-scoped read-only projection computes explicit study minutes, a 30-day evidence heatmap, "
            "current streak, processed mastery trend, paginated business activity, compact profile summary, "
            "deterministic period report and controlled internal deep links from the existing learning event truth."
        ),
        "visible": (
            "After frontend wiring, the learner sees only real study facts with period, calculation and source-event "
            "provenance; an empty account remains empty and a withdrawn resource is shown as unavailable."
        ),
    },
    "backend-tests": {
        "atoms": ["G19-R01", "G19-R02", "G19-R03", "G19-R04", "G19-R05", "G19-R07", "G19-R08", "G20-R03"],
        "files": ["tests/test_f8_t04_personal_activity.py"],
        "result": (
            "Isolated SQLite tests prove explicit duration accounting, evidence-only heatmap and streak, processed-only "
            "mastery trend, owner/course isolation, honest empty truth, stable pagination and controlled deep links."
        ),
        "visible": "Personal profile facts remain reproducible from owned learning events, while reading, filtering and opening history add no learning evidence.",
    },
    "profile-ui": {
        "atoms": ["G19-R01", "G19-R02", "G19-R03", "G19-R04", "G19-R05", "G19-R06", "G19-R07", "G19-R08", "G20-R03"],
        "files": ["frontend/src/api/m5.js", "frontend/src/views/ProfileDashboard.vue", "frontend/src/components/LearningTrendChart.vue"],
        "result": (
            "The profile route follows the figure-29 reading order: identity and actions, four facts plus heatmap, "
            "trend and recent activity, then compact profile/report entrances with honest loading, empty and failure states."
        ),
        "visible": "The learner can understand recent effort and the next useful action without opening the full profile or reading a card wall.",
    },
    "history-ui": {
        "atoms": ["G19-R04", "G19-R06", "G19-R07", "G19-R08", "G20-R03"],
        "files": ["frontend/src/views/History.vue"],
        "result": (
            "The profile history deep link uses course, period and object-type filters, a stable event timeline and a "
            "source/context detail pane; legacy engineering language and unaudited profile rollback are removed."
        ),
        "visible": "The learner can find a real learning object, understand whether it affected mastery and continue from its owning route.",
    },
    "focused-tests": {
        "atoms": ["G19-R01", "G19-R02", "G19-R03", "G19-R04", "G19-R05", "G19-R06", "G19-R07", "G19-R08", "G20-R03"],
        "files": ["tests/test_f8_t04_personal_activity.py", "tests/test_f8_t04_profile_frontend_contract.py"],
        "result": (
            "Focused contracts verify real duration and trend calculations, empty truth, owner/course scope, pagination, "
            "safe deep links, no-read writes, figure-29 layout, frozen visual rules and the eight-entry navigation boundary."
        ),
        "visible": "Regressions that invent study facts, expose engineering controls or break the profile/history structure are rejected automatically.",
    },
    "browser-e2e": {
        "atoms": ["G19-R01", "G19-R02", "G19-R03", "G19-R04", "G19-R05", "G19-R06", "G19-R07", "G19-R08", "G20-R03"],
        "files": ["scripts/e2e_f8_t04_profile_history.py"],
        "result": (
            "The isolated browser journey compares profile and history facts, opens a source object, checks an empty "
            "account and verifies both frozen desktop sizes, visual rules and zero-write browsing."
        ),
        "visible": "The complete profile-to-history-to-source journey remains readable, traceable and reversible on both required desktop sizes.",
    },
}


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def atomic_write(path: Path, payload: dict) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", choices=sorted(BATCHES))
    parser.add_argument("--verification", action="append", default=[])
    args = parser.parse_args()
    definition = BATCHES[args.batch]
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    entries = {entry["atomic_requirement_id"]: entry for entry in ledger["entries"]}
    missing = sorted(set(definition["atoms"]) - set(entries))
    if missing:
        raise RuntimeError(f"F8-T04 ledger atoms changed: {missing}")
    stamp = datetime.now(timezone.utc).isoformat()
    implementation = [
        f"F8-T04 {args.batch} batch at {stamp}: {', '.join(definition['files'])}",
        definition["result"],
    ]
    for atom_id in definition["atoms"]:
        realization = entries[atom_id]["realization"]
        realization["status"] = "IMPLEMENTATION_IN_PROGRESS"
        realization["implementation_evidence"] = append_unique(
            list(realization.get("implementation_evidence") or []), implementation,
        )
        realization["verification_evidence"] = append_unique(
            list(realization.get("verification_evidence") or []), args.verification,
        )
        realization["user_visible_result"] = definition["visible"]
    batches = ledger.setdefault("execution_batches", [])
    record = next((item for item in batches if item.get("id") == args.batch), None)
    if record is None:
        record = {"id": args.batch}
        batches.append(record)
    record.update({
        "status": "IMPLEMENTED_PENDING_FINAL_VERIFICATION",
        "updated_at": stamp,
        "atoms": definition["atoms"],
        "files": definition["files"],
        "result": definition["result"],
        "verification": args.verification,
    })
    atomic_write(LEDGER, ledger)
    print(json.dumps({"status": "BATCH_RECORDED", "batch": args.batch}, ensure_ascii=False))


if __name__ == "__main__":
    main()
