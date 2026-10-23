from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


COURSE_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".pdf", ".pptx", ".docx",
    ".ipynb", ".py", ".csv", ".json", ".tex",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _license_kind(text: str) -> str:
    normalized = " ".join(text.lower().split())
    if "gnu general public license" in normalized and "version 3" in normalized:
        return "GPL-3.0"
    if "attribution-noncommercial-sharealike 4.0" in normalized or "cc by-nc-sa 4.0" in normalized:
        return "CC-BY-NC-SA-4.0"
    if "clear bsd license" in normalized:
        return "Clear-BSD"
    if "mit license" in normalized:
        return "MIT"
    return "unrecognized"


def _git_revision(repo: Path) -> str:
    if not (repo / ".git").exists():
        return ""
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and len(value) == 40 else ""


def _repo_entry(source: dict[str, Any], repo: Path) -> dict[str, Any]:
    license_paths = sorted(
        path for path in repo.iterdir()
        if path.is_file() and path.name.upper().startswith(("LICENSE", "COPYING"))
    ) if repo.exists() else []
    licenses = []
    detected = set()
    for path in license_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        kind = _license_kind(text)
        detected.add(kind)
        licenses.append({
            "path": path.relative_to(repo).as_posix(),
            "sha256": _sha256(path),
            "detected_spdx": kind,
        })

    extension_counts: Counter[str] = Counter()
    material_bytes = 0
    if repo.exists():
        for path in repo.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            suffix = path.suffix.lower()
            if suffix in COURSE_EXTENSIONS:
                extension_counts[suffix or "[none]"] += 1
                material_bytes += path.stat().st_size

    clear_permissive = bool(detected & {"MIT", "Clear-BSD"})
    obligations = []
    if "GPL-3.0" in detected:
        obligations.append("copyleft_and_source_distribution_review")
    if "CC-BY-NC-SA-4.0" in detected:
        obligations.extend(["attribution", "noncommercial_only", "sharealike"])
    if clear_permissive:
        obligations.extend(["retain_license", "retain_copyright_notice"])

    if clear_permissive:
        status = "approved_default_course_candidate"
        reason = "recognized permissive license file is present and hashed"
    elif detected & {"GPL-3.0", "CC-BY-NC-SA-4.0"}:
        status = "manual_obligation_review_required"
        reason = "license is recognized but redistribution obligations require explicit acceptance"
    elif not licenses:
        status = "blocked_no_local_license"
        reason = "no repository-root license file is available for distribution review"
    else:
        status = "blocked_unrecognized_license"
        reason = "license file exists but automated classifier cannot establish distribution terms"

    return {
        **source,
        "local_path": repo.as_posix(),
        "local_repo_present": repo.exists(),
        "git_revision": _git_revision(repo),
        "license_files": licenses,
        "material_file_counts": dict(sorted(extension_counts.items())),
        "material_bytes": material_bytes,
        "default_course_eligibility": status,
        "eligibility_reason": reason,
        "obligations": sorted(set(obligations)),
    }


def build_audit(project_root: Path) -> dict[str, Any]:
    manifest_path = project_root / "data" / "manifest" / "source_manifest.jsonl"
    sources = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entries = []
    raw_root = project_root / "data" / "raw" / "github_repos"
    for source in sources:
        if source.get("kind") == "git":
            entries.append(_repo_entry(source, raw_root / source["key"]))
        else:
            entries.append({
                **source,
                "local_path": "",
                "local_repo_present": False,
                "git_revision": "",
                "license_files": [],
                "material_file_counts": {},
                "material_bytes": 0,
                "default_course_eligibility": "external_reference_only",
                "eligibility_reason": "direct source is not bundled as a reviewed repository",
                "obligations": ["verify_upstream_terms_at_import_time"],
            })
    statuses = Counter(item["default_course_eligibility"] for item in entries)
    return {
        "schema_version": "edumatrix.course-source-audit.v1",
        "source_manifest_sha256": _sha256(manifest_path),
        "source_count": len(entries),
        "local_git_source_count": sum(item["local_repo_present"] for item in entries),
        "status_counts": dict(sorted(statuses.items())),
        "default_course_allowlist": sorted(
            item["key"]
            for item in entries
            if item["default_course_eligibility"] == "approved_default_course_candidate"
        ),
        "sources": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit EduMatrix course source and license inventory")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/manifest/course_source_audit.json"),
    )
    args = parser.parse_args()
    root = args.project_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    report = build_audit(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "source_count": report["source_count"],
        "status_counts": report["status_counts"],
        "allowlist": report["default_course_allowlist"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
