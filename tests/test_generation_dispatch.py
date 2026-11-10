"""Fault-injected dispatcher checks; these are not live model quality results."""
from datetime import timedelta
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBUser, DBGenerationTask, DBTaskStep, DBTaskEvent, DBLearningEvent
from app.competition_demo_seed import seed_competition_demo
from app import resource_bundles as bundles
from app import generation_dispatch as dispatch
from tests.test_pr_01_semantic_resource_generation import _FakeLiveBackend


@pytest.fixture
def runtime(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dispatch.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        seed_competition_demo(db)
        db.commit()
    yield factory
    engine.dispose()


def create(factory, key="auto-resource-test", submit=True, types=("code_sandbox",)):
    with factory() as db:
        actor = db.query(DBUser).filter_by(username="lzz").one()
        job = bundles.create_generation_job(db, actor, course_id="demo-course-rag-trust-v1",
            knowledge_point_id="demo-kp-07", profile_snapshot_id="demo-profile-lzz-v1",
            idempotency_key=key, scope="single" if len(types) == 1 else "bundle",
            items=[{"type": kind, "title": kind, "source_ref_ids": ["demo-ref-07"]} for kind in types])
        if submit:
            dispatch.submit_resource_job(db, actor, job["job_id"])
        db.commit()
        return job["job_id"]


def run_next(factory):
    with factory() as db:
        claim = dispatch.claim_resource_job(db)
    assert claim
    dispatch.run_claimed_resource_job(*claim, session_factory=factory)
    return claim


def test_executable_code_with_failed_required_checks_is_repaired(runtime, monkeypatch):
    from app import code_sandbox
    attempts = []
    async def validation(content):
        attempts.append(content)
        return {'status': 'success', 'stdout': 'actual output', 'checks': [
            {'id': 'required', 'passed': len(attempts) > 1, 'detail': 'Required numerical result missing'}]}
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            result = json.loads(await super().generate(system, user, role=role))
            if role == 'resource_generator':
                result['narrative'] = f'计算结果第{len(attempts)+1}次'
            return json.dumps(result)
    monkeypatch.setattr(code_sandbox, 'validate_generated_code', validation)
    monkeypatch.setattr(bundles, '_real_model_backend', lambda: Backend())
    task_id = create(runtime, 'required-check-failure')
    run_next(runtime)
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).automation_state == 'queued'
        assert not db.query(DBTaskEvent).filter_by(task_id=task_id, event_type='publish.completed').first()
        failed = db.query(DBTaskStep).filter_by(task_id=task_id, error_code='resource_generation.code_execution_invalid').first()
        assert failed and 'Required numerical result missing' in failed.error_message
    run_next(runtime)
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).status == 'completed'
    assert len(attempts) == 2


def test_planner_network_failure_resumes_original_job_before_generating(runtime, monkeypatch):
    calls = []
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            calls.append(role)
            if role == 'resource_planner' and calls.count(role) == 1:
                raise RuntimeError('HTTP 503 planner unavailable')
            return await super().generate(system, user, role=role)
    monkeypatch.setattr(bundles, '_real_model_backend', lambda: Backend())
    task_id = create(runtime, 'planner-automatic-recovery')
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.automation_state == 'retry_wait'
        assert 'resource_generator' not in calls
        assert not db.query(DBTaskEvent).filter_by(task_id=task_id, event_type='publish.completed').first()
        # Advance only the synthetic test clock, not a live task.
        task.next_attempt_at = dispatch._utcnow()
        db.commit()
    run_next(runtime)
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).automation_state == 'completed'
        assert db.query(DBTaskEvent).filter_by(task_id=task_id, event_type='resource_generation.auto_recovery').count() == 1
    assert calls.count('resource_planner') == 2
    assert calls.count('resource_generator') == 1


@pytest.mark.parametrize('samples', [401, 402, 403, 429, 500, 503])
def test_teaching_quantities_are_not_http_failures(samples):
    assert dispatch.classify_failure('resource_generation.review_rejected',
        f'训练样本{samples}，对照基准未保持一致。') == 'content'
    assert dispatch.classify_failure('ValueError', f'训练样本{samples}') == 'application'
    assert dispatch.classify_failure('RuntimeError', f'HTTP {samples} service failed') == (
        'configuration' if samples in {401,402,403} else 'transport')


def test_resource_namespace_does_not_make_application_errors_source_failures():
    assert dispatch.classify_failure('resource_generation.idempotency_conflict', '请求冲突') == 'application'
    assert dispatch.classify_failure('resource_generation.source_snapshot_changed', '来源更新') == 'source'


def test_automatic_repair_after_reset_keeps_distinct_saved_revisions(runtime, monkeypatch):
    reviews, generations = [], []
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            if role == 'resource_review_adjudicator':
                return json.dumps({'decisions': [{'issue_id': f['issue_id'], 'verdict': 'confirmed',
                    'reason': '合成缺失条件', 'fix': f['fix']} for f in json.loads(user)['findings']]})
            result = json.loads(await super().generate(system, user, role=role))
            if role == 'resource_generator':
                generations.append(result)
                result['narrative'] = f'候选{len(generations)}：核对阈值与标签。'
            if role == 'resource_reviewer':
                reviews.append(result)
                if len(reviews) <= 2:
                    result.update(approved=False, rejectedTypes=['code_sandbox'], findings=[{
                        'resourceType': 'code_sandbox', 'location': 'instructions',
                        'issue': f'缺少条件{len(reviews)}', 'evidence': '合成注错',
                        'fix': f'补条件{len(reviews)}', 'severity': 'task_blocked'}])
            return json.dumps(result)
    monkeypatch.setattr(bundles, '_real_model_backend', lambda: Backend())
    task_id = create(runtime, 'repair-after-deployment-reset')
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.automation_state == 'queued'
        # Reproduce a deployment recovery clearing the attempt counter. The
        # real saved revision and original resource versions stay in place.
        task.automation_context = {'attempts': 0}
        db.commit()
    run_next(runtime)
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).automation_state == 'queued'
        events = db.query(DBTaskEvent).filter_by(task_id=task_id,
            event_type='resource_generation.revision.requested').all()
        assert len(events) == 2
        assert len({event.payload['idempotency_key'] for event in events}) == 2
    run_next(runtime)
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).status == 'completed'
        assert len(db.query(DBTaskStep).filter_by(task_id=task_id).all()) == 3


def test_only_submitted_jobs_run_and_claim_is_exclusive_after_restart(runtime):
    historical = create(runtime, "historical-resource", submit=False)
    task_id = create(runtime)
    with runtime() as first, runtime() as second:
        claim = dispatch.claim_resource_job(first)
        assert claim[0] == task_id
        assert dispatch.claim_resource_job(second) is None
        assert second.get(DBGenerationTask, historical).automation_state == ""
        task = first.get(DBGenerationTask, task_id)
        task.lease_expires_at = dispatch._utcnow() - timedelta(seconds=1)
        first.commit()
        replacement = dispatch.claim_resource_job(second)
        assert replacement[0] == task_id and replacement[1] != claim[1]
        assert not dispatch.renew_lease(first, *claim)
        assert dispatch.renew_lease(second, *replacement)


def test_active_learning_feedback_precedes_queued_bundles_without_preempting_work(runtime):
    from app import learning_generation_jobs as jobs
    first_bundle = create(runtime, 'earlier-bundle')
    next_bundle = create(runtime, 'later-bundle')
    with runtime() as db:
        in_flight = dispatch.claim_resource_job(db)
        assert in_flight[0] == first_bundle
        actor = db.query(DBUser).filter_by(username='lzz').one()
        feedback = jobs.queue_task(db, actor, course_id='demo-course-rag-trust-v1',
            capability='feynman.action', request={'session_id':'synthetic-session','action':'evaluate_round1'},
            key='feedback-after-bundle')['id']
        inquiry = jobs.queue_task(db, actor, course_id='demo-course-rag-trust-v1',
            capability='learning_inquiry.prepare',request={'attempt_id':'synthetic-attempt'},
            key='inquiry-after-feedback')['id']
        assert dispatch.claim_resource_job(db)[0] == feedback
        assert dispatch.claim_resource_job(db)[0] == inquiry
        assert dispatch.claim_resource_job(db)[0] == next_bundle
        assert dispatch.renew_lease(db,*in_flight)
        assert dispatch.claim_resource_job(db) is None


def test_review_account_failure_is_kept_alongside_generation_error_and_not_reused_next_attempt(runtime):
    from app.m1_repository import append_task_event
    task_id = create(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        _, latest = bundles._task_steps(db, task_id)
        step = next(iter(latest.values()))
        step.status, step.error_code, step.error_message = 'failed', 'resource_generation.output_invalid', '缺字段'
        append_task_event(db, task_id=task_id, event_type='review_gate.failed',
                          payload={'error_code':'service_auth_failed','error_message':'HTTP 402'})
        failures = dispatch._failure_details(db, task)
        assert {dispatch.classify_failure(row['code'], row['message']) for row in failures} == {'content', 'configuration'}
        append_task_event(db, task_id=task_id, event_type='resource_generation.auto_recovery', payload={'action':'queued'})
        assert len(dispatch._failure_details(db, task)) == 1


def test_rejected_resource_is_automatically_revised_and_original_retained(runtime, monkeypatch):
    generations, reviews = [], []
    learning_events = []
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            if role == "resource_review_adjudicator":
                return json.dumps({"decisions": [{"issue_id": finding["issue_id"],
                    "verdict": "confirmed", "reason": "合成错误需补齐阈值说明。", "fix": "补阈值说明"}
                    for finding in json.loads(user)["findings"]]})
            result = json.loads(await super().generate(system, user, role=role))
            if role == "resource_generator":
                generations.append(json.loads(user))
                result["narrative"] = f"第{len(generations)}次正文：对照输入检查阈值。"
            if role == "resource_reviewer":
                reviews.append(json.loads(user))
                if len(reviews) == 1:
                    # Learning can continue in another resource while this job
                    # is being reviewed. Its repair must retain its own basis.
                    with runtime() as other:
                        actor = other.query(DBUser).filter_by(username='lzz').one()
                        event = DBLearningEvent(owner_public_id=actor.public_id,
                            legacy_student_id=actor.username, course_id='demo-course-rag-trust-v1',
                            event_type='quiz.submitted', source='test', trace_id='learning-during-repair',
                            object_type='knowledge_point', object_id='demo-kp-07', action='submit',
                            context_ref={'knowledgePointId': 'demo-kp-07'}, evidence_strength=0.8,
                            evidence_status='accepted', evidence_reason='Synthetic learning during generation',
                            mastery_eligible=True, completion_effect='progress',
                            payload={'knowledge_point_id': 'demo-kp-07'})
                        other.add(event)
                        other.commit()
                        learning_events.append(event.id)
                    result.update(approved=False, rejectedTypes=["code_sandbox"], findings=[{
                        "resourceType": "code_sandbox", "location": "instructions", "issue": "缺少阈值解释",
                        "evidence": "合成注错：要求对照阈值", "fix": "补阈值说明", "severity": "task_blocked"}])
            return json.dumps(result, ensure_ascii=False)
    monkeypatch.setattr(bundles, "_real_model_backend", lambda: Backend())
    task_id = create(runtime)
    with runtime() as db:
        original_context = bundles._generation_manifest(db, task_id)['context']
    run_next(runtime)
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).automation_state == "queued"
        first = db.query(DBTaskStep).filter_by(task_id=task_id, attempt=1).one()
        assert first.status == "failed" and first.output_artifact_version_id
        first_version = first.output_artifact_version_id
        assert bundles._generation_manifest(db, task_id)['context'] == original_context
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.status == "completed", task.automation_context
        assert task.automation_state == "completed"
        steps = db.query(DBTaskStep).filter_by(task_id=task_id).order_by(DBTaskStep.attempt).all()
        assert steps[0].output_artifact_version_id == first_version
        assert steps[-1].output_artifact_version_id != first_version
        assert "阈值" in steps[-1].input_summary
        assert len(generations) == 2 and len(reviews) == 2
    later_task = create(runtime, 'new-generation-after-learning', submit=False)
    with runtime() as db:
        later_context = bundles._generation_manifest(db, later_task)['context']
        assert learning_events[0] in later_context['recent_event_ids']
        assert learning_events[0] not in original_context['recent_event_ids']


def test_review_network_retry_reuses_draft_and_configuration_failure_does_not_poll(runtime, monkeypatch):
    calls = []
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            calls.append(role)
            if role == "resource_reviewer" and calls.count(role) == 1:
                raise RuntimeError("HTTP 503 temporary service unavailable")
            return await super().generate(system, user, role=role)
    monkeypatch.setattr(bundles, "_real_model_backend", lambda: Backend())
    task_id = create(runtime)
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.automation_state == "retry_wait", task.automation_context
        assert dispatch.claim_resource_job(db) is None
        task.next_attempt_at = dispatch._utcnow()
        db.commit()
    run_next(runtime)
    assert calls.count("resource_generator") == 1
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).status == "completed"

    blocked_id = create(runtime, "account-block")
    class Blocked(_FakeLiveBackend):
        async def generate(self, *args, **kwargs):
            raise RuntimeError("HTTP 402 insufficient balance")
    monkeypatch.setattr(bundles, "_real_model_backend", lambda: Blocked())
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, blocked_id)
        assert task.automation_state == "waiting_configuration", task.automation_context
        dispatch.resume_changed_configuration(db)
        assert dispatch.claim_resource_job(db) is None
        actor = db.query(DBUser).filter_by(username="lzz").one()
        dispatch.submit_resource_job(db, actor, blocked_id)
        assert task.automation_state == "waiting_configuration"
    create(runtime, "another-job")
    assert dispatch.GenerationDispatcher(runtime)._tick() == []
    monkeypatch.setattr(dispatch, "configuration_signature", lambda: "new-configuration")
    with runtime() as db:
        dispatch.resume_changed_configuration(db)
        assert db.get(DBGenerationTask, blocked_id).automation_state == "queued"


def test_false_positive_is_resolved_against_saved_draft_without_regeneration(runtime, monkeypatch):
    calls = []
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            calls.append(role)
            if role == "resource_review_adjudicator":
                data = json.loads(user)
                return json.dumps({"decisions": [{"issue_id": finding["issue_id"],
                    "verdict": "false_positive", "candidate_quote": "print('model-generated')",
                    "reason": "原稿已包含可运行代码和输出检查，所指缺项不存在。", "fix": "", "source_evidence": []}
                    for finding in data["findings"]]})
            result = json.loads(await super().generate(system, user, role=role))
            if role == "resource_reviewer":
                result.update(approved=False, rejectedTypes=["code_sandbox"], findings=[{
                    "resourceType": "code_sandbox", "location": "files", "issue": "没有代码",
                    "evidence": "合成误报", "fix": "添加代码", "severity": "task_blocked"}])
            return json.dumps(result, ensure_ascii=False)
    monkeypatch.setattr(bundles, "_real_model_backend", lambda: Backend())
    task_id = create(runtime)
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.status == "completed", task.automation_context
        assert calls.count("resource_generator") == 1
        assert db.query(DBTaskStep).filter_by(task_id=task_id).count() == 1
        raw = db.query(DBTaskEvent).filter_by(task_id=task_id, event_type="resource_generation.review_result").one()
        resolved = db.query(DBTaskEvent).filter_by(task_id=task_id, event_type="resource_generation.review_adjudicated").one()
        assert raw.payload["review"]["approved"] is False
        assert resolved.payload["review"]["review_decisions"][0]["verdict"] == "false_positive"


def test_generation_http402_is_not_retried_as_json_repair(runtime, monkeypatch):
    calls = []
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            calls.append(role)
            if role == "resource_generator":
                raise RuntimeError("HTTP 402 insufficient balance")
            return await super().generate(system, user, role=role)
    monkeypatch.setattr(bundles, "_real_model_backend", lambda: Backend())
    task_id = create(runtime)
    run_next(runtime)
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).automation_state == "waiting_configuration"
    assert calls.count("resource_generator") == 1


def test_single_training_prepares_missing_companions_and_keeps_original_request(runtime):
    task_id = create(runtime, "single-training", types=("training_task",))
    with runtime() as db:
        actor = db.query(DBUser).filter_by(username="lzz").one()
        manifest = bundles._generation_manifest(db, task_id)
        assert manifest["selected_resource_types"] == ["training_task"]
        assert {item["type"] for item in manifest["items"]} == {"training_task", "code_sandbox", "interactive_model"}
        assert db.query(DBTaskStep).filter_by(task_id=task_id).count() == 3
        dispatch.submit_resource_job(db, actor, task_id)
        assert db.query(DBTaskStep).filter_by(task_id=task_id).count() == 3
    assert create(runtime, "single-training", types=("training_task",)) == task_id


@pytest.mark.parametrize('broken_code,error_fragment', [
    ('print(1/0)', 'division'),
    ('print(sum(training_values))', 'training_values'),
])
def test_runtime_failure_is_repaired_before_the_code_is_published(runtime, monkeypatch, broken_code, error_fragment):
    generations = []
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            result = json.loads(await super().generate(system, user, role=role))
            if role == "resource_generator":
                generations.append(json.loads(user))
                result["starterCode"] = broken_code if len(generations) == 1 else "training_values = [1,2,3]\nprint('model-generated', sum(training_values))"
            return json.dumps(result, ensure_ascii=False)
    monkeypatch.setattr(bundles, "_real_model_backend", lambda: Backend())
    task_id = create(runtime, "runtime-repair")
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.automation_state == "queued", task.automation_context
        assert not db.query(DBTaskEvent).filter_by(task_id=task_id, event_type="publish.completed").first()
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.status == "completed", task.automation_context
        assert error_fragment in generations[1]["revision_feedback"]
        assert db.query(DBTaskStep).filter_by(task_id=task_id).count() == 2


def test_independent_review_opens_resource_while_sibling_is_still_being_checked(runtime, monkeypatch):
    from app.database import DBArtifact
    from app.m5_resources import resource_generation_blocker
    observed = []
    task_id = create(runtime, "partial-publish", types=("code_sandbox", "feynman"))
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            data = json.loads(user)
            if role == "resource_reviewer" and len(data.get("candidates", [])) > 1:
                with runtime() as other:
                    task = other.get(DBGenerationTask, task_id)
                    artifact = other.query(DBArtifact).filter_by(creating_task_id=task_id, artifact_type="feynman").one()
                    assert task.status != "completed"
                    assert not resource_generation_blocker(other, artifact)
                    observed.append(artifact.id)
            return await super().generate(system, user, role=role)
    monkeypatch.setattr(bundles, "_real_model_backend", lambda: Backend())
    run_next(runtime)
    assert observed


def test_successful_resource_is_reviewed_while_another_generation_is_offline(runtime, monkeypatch):
    from app.database import DBArtifact
    from app.m5_resources import resource_generation_blocker
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            if role == 'resource_generator' and json.loads(user).get('resource_type') == 'code_sandbox':
                raise RuntimeError('503 Service Unavailable')
            return await super().generate(system, user, role=role)
    monkeypatch.setattr(bundles, '_real_model_backend', lambda: Backend())
    task_id = create(runtime, 'partial-generation-offline', types=('code_sandbox', 'feynman'))
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.automation_state == 'retry_wait', task.automation_context
        artifact = db.query(DBArtifact).filter_by(creating_task_id=task_id, artifact_type='feynman').one()
        assert artifact.status == 'published'
        assert not resource_generation_blocker(db, artifact)
        assert not db.query(DBTaskEvent).filter_by(task_id=task_id, event_type='run.completed').first()


def test_companion_reuse_keeps_same_learning_contract_and_can_revise_immutable_original(runtime, monkeypatch):
    from app.database import DBArtifact, DBArtifactVersion
    monkeypatch.setattr(bundles, '_real_model_backend', lambda: _FakeLiveBackend())
    original_id = create(runtime, 'original-companion')
    run_next(runtime)
    training_id = create(runtime, 'reuse-companion', types=('training_task',))
    with runtime() as db:
        original = db.query(DBArtifact).filter_by(creating_task_id=original_id).one()
        old_id = original.current_version_id
        old_content = db.get(DBArtifactVersion, old_id).content
        _, latest = bundles._task_steps(db, training_id)
        code = latest[bundles.GENERATION_RESOURCE_TYPES.index('code_sandbox') + 1]
        assert code.status == 'succeeded' and code.output_artifact_version_id == old_id
        actor = db.query(DBUser).filter_by(username='lzz').one()
        # Simulate a current review rejecting the reused companion. The new
        # task owns the repair; the earlier published resource stays unchanged.
        for step in latest.values():
            if step.status != 'succeeded':
                step.status = 'failed'
                step.error_code = 'resource_generation.dependency_failed'
        code.status = 'failed'
        code.error_code = 'resource_generation.review_rejected'
        task = db.get(DBGenerationTask, training_id)
        task.status = 'failed'
        db.commit()
        bundles.revise_generation_job(db, actor, training_id, feedback='补充比较所需条件。',
            resource_types=['code_sandbox'], idempotency_key='repair-reused-companion')
        _, revised = bundles._task_steps(db, training_id)
        assert revised[code.sequence].attempt == 2
        assert revised[code.sequence].output_artifact_version_id is None
        assert original.current_version_id == old_id
        assert db.get(DBArtifactVersion, old_id).content == old_content
        different = bundles.create_generation_job(db, actor, course_id='demo-course-rag-trust-v1',
            knowledge_point_id='demo-kp-07', profile_snapshot_id='demo-profile-lzz-v1',
            idempotency_key='different-learning-contract', scope='single', learning_goal='另一套数据的独立比较',
            user_instruction='本次训练样本与原表不同。',
            items=[{'type':'training_task', 'title':'实训', 'source_ref_ids':['demo-ref-07']}])
        dispatch.submit_resource_job(db, actor, different['job_id'])
        _, latest = bundles._task_steps(db, different['job_id'])
        assert latest[code.sequence].status == 'queued'


def test_source_update_rebinds_only_affected_work_and_preserves_old_snapshot(runtime, monkeypatch):
    from app.database import DBSourceRef
    task_id = create(runtime, "source-update")
    with runtime() as db:
        original = bundles._generation_manifest(db, task_id)["input_snapshot"]
        source = db.get(DBSourceRef, "demo-ref-07")
        source.quote += "\n新增的课程说明。"
        source.content_hash = "new-source-version"
        db.commit()
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            result = json.loads(await super().generate(system, user, role=role))
            if role == "resource_planner":
                result["activeRequirements"] = {"learning_goal": "按当前来源解释误差", "shared": [], "by_resource": {}}
            return json.dumps(result, ensure_ascii=False)
    monkeypatch.setattr(bundles, "_real_model_backend", lambda: Backend())
    run_next(runtime)
    with runtime() as db:
        task = db.get(DBGenerationTask, task_id)
        assert task.automation_state == "queued", task.automation_context
        current = bundles._generation_manifest(db, task_id)["input_snapshot"]
        assert current["source_snapshot_hashes"] != original["source_snapshot_hashes"]
        requested = db.query(DBTaskEvent).filter_by(task_id=task_id, event_type="resource_generation.requested").one()
        assert requested.payload["manifest"]["input_snapshot"] == original
    run_next(runtime)
    with runtime() as db:
        assert db.get(DBGenerationTask, task_id).status == "completed"


@pytest.mark.parametrize("action", ["cancel", "replace_owner"])
def test_late_model_response_cannot_publish_after_cancellation_or_lease_replacement(runtime, monkeypatch, action):
    task_id = create(runtime)
    class Backend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            result = await super().generate(system, user, role=role)
            if role == "resource_generator":
                with runtime() as other:
                    task = other.get(DBGenerationTask, task_id)
                    actor = other.query(DBUser).filter_by(username="lzz").one()
                    if action == "cancel":
                        bundles.cancel_generation_job(other, actor, task_id)
                    else:
                        task.execution_token = "another-executor"
                    other.commit()
            return result
    monkeypatch.setattr(bundles, "_real_model_backend", lambda: Backend())
    run_next(runtime)
    with runtime() as db:
        assert db.query(DBTaskStep).filter_by(task_id=task_id).one().output_artifact_version_id is None
        assert not db.query(DBTaskEvent).filter_by(task_id=task_id, event_type="publish.completed").first()
        task = db.get(DBGenerationTask, task_id)
        assert task.status == "cancelled" if action == "cancel" else task.execution_token == "another-executor"
