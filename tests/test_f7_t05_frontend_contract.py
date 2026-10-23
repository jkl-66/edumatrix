from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"
SOURCE_CITATION = FRONTEND / "components" / "SourceCitation.vue"
AGENT_TIMELINE = FRONTEND / "components" / "AgentTimeline.vue"
CHAT = FRONTEND / "views" / "Chat.vue"
READER = FRONTEND / "views" / "KnowledgeDocumentReader.vue"
HANDOUT = FRONTEND / "views" / "HandoutWorkspace.vue"
CHAT_STORE = FRONTEND / "stores" / "chat.js"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_source_component_resolves_exact_reader_route_and_return_path() -> None:
    citation = source(SOURCE_CITATION)

    for marker in (
        "getCanonicalSourceRef",
        "sourceRefId",
        "sourceDocumentId",
        "documentVersion",
        "chapterTitle",
        "pageNumber",
        "charStart",
        "charEnd",
        "imageRegion",
        "locationLabel",
        "reasonCode",
        "routeWithReturnTo",
        "params.set('return_to', props.returnTo)",
        'data-testid="canonical-source-citation"',
        ':data-source-ref-id="citation.id"',
        "来源没有可返回的原文位置",
    ):
        assert marker in citation
    assert "router.push(target)" in citation
    assert "if (!normalized.available)" in citation


def test_agent_timeline_uses_only_server_facts_and_four_public_stages() -> None:
    timeline = source(AGENT_TIMELINE)

    assert "const roleOrder = ['analysis', 'generation', 'validation', 'decision']" in timeline
    for marker in (
        "inputRefs",
        "candidateSummary",
        "disagreement",
        "validation",
        "revision",
        "decisionSummary",
        "冻结演示结果（非本次实时运行）",
        "历史已完成回答（非本次结果）",
        'data-testid="agent-audit-timeline"',
    ):
        assert marker in timeline
    for fabricated in (
        "setInterval",
        "setTimeout",
        "Math.random",
        "progress >=",
        "progress >",
        "tenAgents",
    ):
        assert fabricated not in timeline


def test_public_agent_ui_rejects_private_reasoning_and_raw_runtime_fields() -> None:
    public_ui = "\n".join(source(path) for path in (AGENT_TIMELINE, CHAT, READER, HANDOUT)).lower()

    for forbidden in (
        "chain_of_thought",
        "reasoning_content",
        "system_prompt",
        "raw_trace",
        "raw_log",
        "api_key",
        "完整思维链",
    ):
        assert forbidden not in public_ui


def test_chat_reader_and_handout_share_source_and_audit_components() -> None:
    chat = source(CHAT)
    reader = source(READER)
    handout = source(HANDOUT)

    assert "import SourceCitation" in chat and "import AgentTimeline" in chat
    assert ':return-to="route.fullPath"' in chat
    assert 'data-testid="chat-source-list"' in chat
    assert 'data-testid="chat-agent-audit"' in chat
    assert "evidenceMessage.value?.agentAudit" in chat
    assert "evidenceMessage.value?.streamCheckpoint?.agentAudit" in chat

    assert "import SourceCitation" in reader and "import AgentTimeline" in reader
    assert "route.query.source_ref_id" in reader
    assert "route.query.chapter_id" in reader
    assert "route.query.char_start" in reader
    assert "readerDoc.value.source_document_id || sourceDocumentId.value" in reader
    assert ':source="selection.answer_source || selection.source"' in reader
    assert ':audit="selection.agent_audit"' in reader
    assert "const returnTo = String(route.query.return_to || '')" in reader

    assert "import SourceCitation" in handout
    assert "sourceForFootnote(item)" in handout
    assert ':return-to="route.fullPath"' in handout
    assert 'v-for="source in sourceRefs"' in handout


def test_chat_store_persists_server_audit_for_every_stream_terminal_state() -> None:
    store = source(CHAT_STORE)

    assert "function eventAgentAudit(data, message)" in store
    assert "data?.agent_audit" in store
    assert "data?.agentAudit" in store
    for event in ("progress", "checkpoint", "complete", "stopped", "error"):
        assert f"event === '{event}'" in store
    assert store.count("agentAudit: eventAgentAudit") >= 5
    for fabricated in ("setInterval", "inferAgent", "deriveAgentFromProgress"):
        assert fabricated not in store


def test_f7_t02_and_f7_t04_layout_and_state_ownership_remain_intact() -> None:
    chat = source(CHAT)
    reader = source(READER)

    assert "grid-template-columns: minmax(190px, 20fr) minmax(540px, 58fr) minmax(230px, 22fr)" in reader
    assert 'aria-label="课程与章节目录"' in reader
    assert 'aria-label="来源、问答与笔记"' in reader
    assert "handleTextSelection" in reader
    assert "finishImageSelection" in reader
    assert "retryDocumentSelectionOcr" in reader
    assert "已恢复上次位置" in reader

    assert "grid-template-columns: 228px minmax(520px, 1fr) 292px" in chat
    assert 'data-testid="focused-chat-workspace"' in chat
    assert "等待解析" in chat
    assert "部分解析失败" in chat
    assert "失败可重试" in chat
    assert "stopActiveResponse" in chat
    assert "continueResponse" in chat
    assert "full_resource_content" not in chat


def test_f1_minimal_visual_contract_is_preserved_without_small_text_or_theme_drift() -> None:
    ui = "\n".join(source(path) for path in (SOURCE_CITATION, AGENT_TIMELINE, CHAT, READER, HANDOUT)).lower()

    for required in (
        "#f5f7f7",
        "#ffffff",
        "#06141b",
        "#11212d",
        "var(--font-sans)",
    ):
        assert required in ui
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "#10b981",
        "#0ea5e9",
        "#8b5cf6",
        "font-size: 10px",
        "font-size: 11px",
        "font-size: 12px",
        "font-size: 13px",
    ):
        assert forbidden not in ui


def test_source_and_audit_views_do_not_write_learning_or_mastery_evidence() -> None:
    ui = "\n".join(source(path) for path in (SOURCE_CITATION, AGENT_TIMELINE, CHAT, READER, HANDOUT))

    for forbidden in (
        "createLearningEvent",
        "updateMastery",
        "completePathTask",
        "unlockExam",
    ):
        assert forbidden not in ui
