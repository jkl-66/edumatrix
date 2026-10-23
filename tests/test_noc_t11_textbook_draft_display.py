from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend/src/views/LearningPathGraph.vue"


def _draft_template(source: str) -> str:
    marker = source.rindex('data-testid="textbook-path-draft"')
    start = source.rfind("<section", 0, marker)
    end = source.index("\n    </section>", marker)
    return source[start:end]


def test_textbook_draft_keeps_only_time_and_core_path_content():
    source = VIEW.read_text(encoding="utf-8")
    draft = _draft_template(source)

    assert "预计 {{ textbookDraft.plan.total_minutes }} 分钟" in draft
    assert "{{ node.estimate_max_minutes }} 分钟" in draft
    assert "{{ node.title }}" in draft
    assert "node.knowledge_points" in draft
    assert "openTextbookSource(node)" in draft

    assert "textbookDraft.plan.version_number" not in draft
    assert "textbookDraft.evidence" not in draft
    assert "textbookGeneration.model" not in draft
    assert "textbookGeneration.error_code" not in draft
    assert "textbookGeneration.personalization_summary" not in draft
    assert "node.reason" not in draft
    assert "textbookDraft.diff" not in draft
    assert "textbookDraft.boundary" not in draft


def test_textbook_draft_keeps_generation_confirmation_and_status_contracts():
    source = VIEW.read_text(encoding="utf-8")
    draft = _draft_template(source)

    assert 'data-testid="generate-textbook-path-draft"' in draft
    assert 'data-testid="confirm-textbook-path-draft"' in draft
    assert 'data-testid="textbook-path-model-status"' in draft
    assert "generateTextbookDraft" in draft
    assert "confirmTextbookDraft" in draft
    assert "deepseek-v4-flash" in draft
    assert "用户确认前仅为草稿" in draft
    assert "模型失败不会改用模板" in draft
