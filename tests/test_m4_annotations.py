from app.database import DBEvaluationAnnotation, DBEvaluationReport
from app.m4_annotations import add_annotation, current_annotations, persist_draft_report, resolve_scoring_annotations
from app.m4_evaluation import AtomicFactAnnotation, calculate_metric_report, load_frozen_benchmark
from app.m4_runs import BlindCaseOutput, record_blind_result, start_evaluation_run, sync_frozen_cases
from tests.test_m4_runs import _session


def test_m4_annotation_and_report_are_persisted_as_unapproved_evidence():
    session, version = _session()
    benchmark = load_frozen_benchmark()
    sync_frozen_cases(session, benchmark=benchmark, domain_version_id=version.id)
    run = start_evaluation_run(
        session,
        benchmark=benchmark,
        trace_id="trace-m4-annotation-001",
        code_version="test-tree",
        model_version="test-double",
    )
    result = record_blind_result(
        session,
        run=run,
        output=BlindCaseOutput(case_id="M0-K01", status="completed", response_text="output"),
    )
    annotation = add_annotation(
        session,
        result=result,
        payload=AtomicFactAnnotation(
            case_id="M0-K01",
            claim_id="claim-1",
            label="supported",
            annotator_ref="annotator-a",
            status="final",
        ),
    )
    replay = add_annotation(
        session,
        result=result,
        payload=AtomicFactAnnotation(
            case_id="M0-K01",
            claim_id="claim-1",
            label="supported",
            annotator_ref="annotator-a",
            status="final",
        ),
    )
    assert replay.id == annotation.id
    assert session.query(DBEvaluationAnnotation).count() == 1

    run.status = "awaiting_annotation"
    session.commit()
    report = calculate_metric_report(
        benchmark,
        outcomes=(),
        fact_annotations=(),
        adaptation_annotations=(),
        coverage_annotations=(),
    )
    persisted = persist_draft_report(
        session,
        run=run,
        benchmark=benchmark,
        report_data=report.model_dump(mode="json"),
    )
    assert persisted.status == "draft"
    assert persisted.approval_ref == ""
    assert persisted.report_data["data"]["publication_authorized"] is False
    assert session.query(DBEvaluationReport).count() == 1


def test_m4_double_annotation_requires_agreement_or_adjudication():
    session, version = _session()
    benchmark = load_frozen_benchmark()
    sync_frozen_cases(session, benchmark=benchmark, domain_version_id=version.id)
    run = start_evaluation_run(
        session,
        benchmark=benchmark,
        trace_id="trace-m4-annotation-002",
        code_version="test-tree",
        model_version="test-double",
    )
    result = record_blind_result(
        session,
        run=run,
        output=BlindCaseOutput(case_id="M0-K01", status="completed", response_text="output"),
    )
    for annotator in ("annotator-a", "annotator-b"):
        add_annotation(
            session,
            result=result,
            payload=AtomicFactAnnotation(
                case_id="M0-K01",
                claim_id="claim-agreed",
                label="supported",
                annotator_ref=annotator,
                status="final",
            ),
        )
    add_annotation(
        session,
        result=result,
        payload=AtomicFactAnnotation(
            case_id="M0-K01",
            claim_id="claim-single",
            label="unsupported",
            annotator_ref="annotator-a",
            status="final",
        ),
    )

    resolved, unresolved = resolve_scoring_annotations(current_annotations(session, run))

    assert [row.annotation_key for row in resolved] == ["claim-agreed"]
    assert len(unresolved) == 1
    assert unresolved[0].endswith("second_annotation_missing")
