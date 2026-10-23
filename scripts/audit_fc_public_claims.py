"""Audit judge-facing EduMatrix claims without treating disclaimers as claims."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC6-07A"
TEXT_FILES = [
    ROOT / "README.md",
    ROOT / "outputs" / "README.md",
    ROOT / "outputs" / "00015352介绍" / "README.md",
    ROOT / "outputs" / "00015352介绍" / "00_评委阅读说明.md",
    ROOT / "outputs" / "EduMatrix_完整技术文档总稿.md",
    ROOT / "outputs" / "EduMatrix_比赛技术文档_事实校正版.md",
    ROOT / "outputs" / "EduMatrix_比赛答辩演示脚本.md",
    ROOT / "outputs" / "EduMatrix_提交包内容说明.md",
    ROOT / "outputs" / "EduMatrix_评委阅读说明.md",
    ROOT / "outputs" / "EduMatrix_测试说明书.md",
    ROOT / "outputs" / "EduMatrix_部署运维说明书.md",
    ROOT / "outputs" / "EduMatrix_软件杯PPT逐页讲解备注.md",
    ROOT / "scripts" / "generate_competition_ppt.py",
]
NEGATIONS = (
    "不宣称", "不代表", "不得", "不能", "不要", "并非", "非当前", "没有", "尚无", "未通过",
    "未获得", "未接入", "不具备", "不等同", "仅为", "仅代表", "待验证", "尚待证明", "还需要", "延期", "建议",
)
RISK_PATTERNS = {
    "fixed_unofficial_threshold": re.compile(
        r"幻觉率\s*[<＜]\s*5\s*%|适配(?:准确)?率\s*(?:>=|≥)\s*85\s*%|(?:知识点)?覆盖率\s*(?:>=|≥)\s*90\s*%",
        re.I,
    ),
    "absolute_quality_claim": re.compile(r"零幻觉|100\s*%\s*(?:稳定|实现|通过|兼容|保证|安全)", re.I),
    "external_proof_claim": re.compile(r"真人专家认证|真实企业(?:接入|认证|验证)|第三方审计(?:通过|认证)|官方达标", re.I),
    "production_security_claim": re.compile(r"生产级(?:安全)?沙箱|完全隔离|企业级安全认证|工业级认证", re.I),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes())
    return digest.hexdigest()


def is_negated(text: str, start: int, end: int) -> bool:
    context = text[max(0, start - 100):min(len(text), end + 180)]
    return any(token in context for token in NEGATIONS)


def inspect_text(label: str, text: str) -> tuple[list[dict], list[dict]]:
    violations: list[dict] = []
    safe_boundaries: list[dict] = []
    lines = text.splitlines() or [text]
    for line_number, line in enumerate(lines, 1):
        for rule, pattern in RISK_PATTERNS.items():
            for match in pattern.finditer(line):
                item = {
                    "file": label,
                    "line": line_number,
                    "rule": rule,
                    "match": match.group(0),
                    "context": line.strip()[:500],
                }
                if is_negated(line, match.start(), match.end()):
                    safe_boundaries.append(item)
                else:
                    violations.append(item)
    return violations, safe_boundaries


def office_text(path: Path) -> str:
    with ZipFile(path) as archive:
        if path.suffix.lower() == ".docx":
            names = [name for name in archive.namelist() if name.startswith("word/") and name.endswith(".xml")]
        else:
            names = [name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
        chunks: list[str] = []
        for name in names:
            raw = archive.read(name).decode("utf-8", "ignore")
            chunks.extend(html.unescape(value) for value in re.findall(r"<(?:w:t|a:t)(?: [^>]*)?>(.*?)</(?:w:t|a:t)>", raw))
        return "\n".join(chunks)


def office_files() -> list[Path]:
    outputs = ROOT / "outputs"
    pruned = {
        "package_smoke_runtime", "package_smoke_runtime_v2-winerror206-discovery", "package_build",
        "_audit_source_tree", "_audit_work_runtime", "recovery", ".venv", "node_modules",
    }
    selected: list[Path] = []
    for base, directories, files in os.walk(outputs, topdown=True, onerror=lambda _: None):
        directories[:] = [item for item in directories if item not in pruned]
        relative = Path(base).relative_to(outputs)
        if len(relative.parts) > 1:
            directories[:] = []
        for name in files:
            path = Path(base) / name
            if path.suffix.lower() in {".docx", ".pptx"} and len(relative.parts) <= 1:
                selected.append(path)
    return sorted(set(selected))


def run(output: Path) -> dict:
    sources: list[dict] = []
    violations: list[dict] = []
    safe_boundaries: list[dict] = []
    unreadable: list[dict] = []

    paths = [path for path in TEXT_FILES if path.is_file()]
    frontend = ROOT / "frontend" / "src"
    paths.extend(path for path in frontend.rglob("*") if path.is_file() and path.suffix.lower() in {".vue", ".js", ".ts"})
    for path in sorted(set(paths)):
        text = path.read_text(encoding="utf-8-sig")
        label = path.relative_to(ROOT).as_posix()
        bad, safe = inspect_text(label, text)
        violations.extend(bad)
        safe_boundaries.extend(safe)
        sources.append({"file": label, "bytes": path.stat().st_size, "sha256": sha256(path), "kind": "text"})

    offices = office_files()
    for path in offices:
        label = path.relative_to(ROOT).as_posix()
        try:
            text = office_text(path)
        except (BadZipFile, OSError) as exc:
            unreadable.append({"file": label, "error": str(exc)})
            continue
        bad, safe = inspect_text(label, text)
        violations.extend(bad)
        safe_boundaries.extend(safe)
        sources.append({"file": label, "bytes": path.stat().st_size, "sha256": sha256(path), "kind": "office"})

    report = {
        "schema_version": "edumatrix.fc6.public-claim-audit.v1",
        "result": "passed" if not violations and not unreadable else "failed",
        "scope": {
            "text_sources": len([item for item in sources if item["kind"] == "text"]),
            "office_documents": len([item for item in sources if item["kind"] == "office"]),
            "historical_archives_and_recovery_copies_excluded": True,
            "formal_packages_rebuilt": False,
        },
        "rules": list(RISK_PATTERNS),
        "violations": violations,
        "safe_boundary_mentions": safe_boundaries,
        "unreadable": unreadable,
        "sources": sources,
        "claim_boundary": [
            "Frozen synthetic courses, organizations, jobs and demonstration roles are not real enterprise proof.",
            "Demonstration sign-off is not external expert certification.",
            "Trusted-local execution is research-only and is not container isolation.",
            "Internal deterministic or synthetic evaluations are not independent human or third-party validation.",
            "No fixed hallucination, adaptation or coverage threshold is an official A3 requirement or a current achieved claim.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = run(args.output.resolve())
    print(json.dumps({
        "result": report["result"],
        "text_sources": report["scope"]["text_sources"],
        "office_documents": report["scope"]["office_documents"],
        "violations": len(report["violations"]),
        "safe_boundary_mentions": len(report["safe_boundary_mentions"]),
        "unreadable": len(report["unreadable"]),
    }, ensure_ascii=False, indent=2))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
