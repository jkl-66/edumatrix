from pathlib import Path


CHAT = Path(__file__).parents[1] / "frontend" / "src" / "views" / "Chat.vue"
TIMELINE = Path(__file__).parents[1] / "frontend" / "src" / "components" / "AgentTimeline.vue"
PRESENTATION = TIMELINE.parent.parent / "utils" / "claimEvidencePresentation.js"


def test_claim_cards_use_one_projection_in_message_and_inspector():
    chat = CHAT.read_text(encoding="utf-8")
    timeline = TIMELINE.read_text(encoding="utf-8")

    assert ':claims="message.claims || message.streamCheckpoint?.claims || []"' in chat
    assert ':claims="evidenceClaims"' in chat
    assert ':source-refs="message.sourceRefs || []"' in chat
    assert ':source-refs="evidenceSourceRefs"' in chat
    assert 'data-testid="claim-evidence-list"' in timeline
    assert 'data-testid="claim-evidence-card"' in timeline
    assert "SourceCitation" in timeline


def test_claim_cards_expose_support_evidence_and_review_fields():
    source = TIMELINE.read_text(encoding="utf-8")
    presentation = PRESENTATION.read_text(encoding="utf-8")
    for support in ("supported", "partially_supported", "contradicted", "unsupported"):
        assert support in presentation
    for field in (
        "sourceRefIds",
        "quote",
        "location",
        "challenger",
        "verifier",
        "revision",
    ):
        assert field in source
    assert "...claimEvidenceStatus(item)" in source
    run_presentation = (PRESENTATION.parent / "agentRunPresentation.js").read_text(encoding="utf-8")
    assert "translatePublicText" in source and "agentRunPresentation.js" in source
    assert "claimSupportLabels[state]" in run_presentation
    assert "{{ claim.label }}" in source
    assert "reasoning_content" not in source.lower()
    assert "api_key" not in source.lower()


def test_timeline_exposes_real_stage_and_resource_progress_from_events():
    source = TIMELINE.read_text(encoding="utf-8")
    assert "{{ normalizedAudit.stageCount }}" not in source
    assert "resourceProgress" in source
    assert 'data-testid="agent-audit-resource-progress"' in source
    assert "resource.item" in source
