"""Scan evaluator-facing Markdown, DOCX, and PPTX files for risky claims."""

from __future__ import annotations

import argparse
import html
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


CLAIMS = {
    "hallucination_target": re.compile(r"幻觉率\s*(?:<|＜|低于)\s*5\s*%?", re.I),
    "adaptation_target": re.compile(r"适配(?:准确)?率\s*(?:>=|≥|高于|不低于)\s*85\s*%?", re.I),
    "coverage_target": re.compile(r"(?:知识点)?覆盖率\s*(?:>=|≥|高于|不低于)\s*90\s*%?", re.I),
    "universal_one_click": re.compile(r"(?:所有|全部|任何).{0,16}(?:环境|功能).{0,16}(?:一键运行|正常使用|完全可用)", re.I),
    "real_enterprise_landing": re.compile(r"(?:真实客户|真实企业).{0,16}(?:落地|部署|应用|使用)", re.I),
}

QUALIFIERS = re.compile(
    r"未(?:完成|验证|达到|达标)|尚未|不能(?:宣称|填写)|不得(?:宣称|写)|不宣称|禁止宣称|"
    r"评测(?:目标|要求)|作为目标|当前没有|待验证|仅为设计|模拟|合成|不代表",
    re.I,
)

SKIP_PARTS = (
    "outputs/M0_阶段0基线与架构契约/",
    "outputs/竞品深度分析/",
    "outputs/_audit_",
    "outputs/package_build/",
    "outputs/package_smoke_runtime/",
    "outputs/recovery/",
)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _classify(text: str) -> str:
    return "qualified" if QUALIFIERS.search(text) else "requires_review"


def _matches(path: str, location: str, text: str) -> list[dict[str, str]]:
    compact = re.sub(r"\s+", " ", html.unescape(text)).strip()
    findings: list[dict[str, str]] = []
    for claim_id, pattern in CLAIMS.items():
        for match in pattern.finditer(compact):
            start = max(0, match.start() - 90)
            end = min(len(compact), match.end() + 90)
            snippet = compact[start:end]
            findings.append(
                {
                    "path": path,
                    "location": location,
                    "claim_id": claim_id,
                    "verdict": _classify(snippet),
                    "snippet": snippet,
                }
            )
    return findings


def _scan_markdown(path: Path, relative: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        findings.extend(_matches(relative, f"line:{line_number}", line))
    return findings


def _xml_text(raw: bytes) -> str:
    root = ElementTree.fromstring(raw)
    return " ".join(node.text for node in root.iter() if node.text)


def _scan_office(path: Path, relative: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if path.suffix.lower() == ".docx":
            parts = [
                name
                for name in names
                if name == "word/document.xml"
                or re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
            ]
        else:
            parts = [name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
            parts.sort(key=lambda value: int(re.search(r"(\d+)", Path(value).stem).group(1)))
        for part in parts:
            findings.extend(_matches(relative, part, _xml_text(archive.read(part))))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="Files or directories to scan")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    files: set[Path] = set()
    for raw_path in args.paths:
        path = Path(raw_path)
        if path.is_dir():
            files.update(
                item
                for item in path.rglob("*")
                if item.is_file() and item.suffix.lower() in {".md", ".docx", ".pptx"}
            )
        elif path.is_file():
            files.add(path)

    findings: list[dict[str, str]] = []
    scanned: list[str] = []
    errors: list[dict[str, str]] = []
    for path in sorted(files):
        relative = _relative(path, root)
        if any(marker in relative for marker in SKIP_PARTS):
            continue
        try:
            scanned.append(relative)
            if path.suffix.lower() == ".md":
                findings.extend(_scan_markdown(path, relative))
            else:
                findings.extend(_scan_office(path, relative))
        except Exception as exc:
            errors.append({"path": relative, "error": f"{type(exc).__name__}: {exc}"})

    report = {
        "files_scanned": len(scanned),
        "requires_review": sum(item["verdict"] == "requires_review" for item in findings),
        "qualified": sum(item["verdict"] == "qualified" for item in findings),
        "errors": errors,
        "findings": findings,
        "scanned_files": scanned,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered)
    return 1 if report["requires_review"] or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
