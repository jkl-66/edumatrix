from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = ROOT / "frontend" / "src" / "views" / "KnowledgeDiscoveryWorkspace.vue"


def _source() -> str:
    return DISCOVERY.read_text(encoding="utf-8")


def test_discovery_projects_format_confidence_capabilities_and_pipeline_stages() -> None:
    source = _source()
    for marker in (
        "formatDetection",
        "formatConfidence",
        "processingPipeline",
        "processingStatus",
        "citationStatus",
        "下载、解析与准入阶段",
        "重新下载并解析",
        "keepFeedback",
        "metadata_and_authorized_ocr",
        "when_authorized",
        "metadata_only",
        "pending_download",
        "data-status=\"entry.status\"",
        "!['summary', 'pipeline'].includes(key)",
    ):
        assert marker in source


def test_discovery_keeps_existing_admission_boundary_and_visual_contract() -> None:
    source = _source().lower()
    for marker in (
        "admitwebsourcecandidate",
        "rejectwebsourcecandidate",
        "withdrawwebsourcecandidate",
        "候选资料尚未进入课程、图谱或检索",
        "var(--color-page)",
        "var(--color-surface)",
        "var(--color-text)",
        "var(--color-accent)",
    ):
        assert marker in source
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "font-size: 10px",
        "font-size: 11px",
        "font-size: 12px",
        "font-size: 13px",
        "createlearningevent",
        "updatemastery",
    ):
        assert forbidden not in source
