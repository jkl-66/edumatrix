from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.diagnostic_api as diagnostic_api
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBDiagnosticBlueprint,
    DBProfileSnapshot,
    DBQuizRecord,
    DBSourceRef,
    DBUser,
)
from app.diagnostic_api import DiagnosticGenerateRequest
from app.diagnostic_generation import (
    DiagnosticBlueprintRequest,
    DiagnosticGenerationError,
    diagnostic_blueprint_payload,
    diagnostic_preflight,
    generate_diagnostic_blueprint,
)
from app.migrations import MIGRATIONS


COURSE_ID = "demo-course-rag-trust-v1"


class _DiagnosticLLM:
    provider = "openai"
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"

    def __init__(self):
        self.calls = []

    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls.append(role)
        payload = json.loads(user_prompt)
        if role == "入学诊断出题" and payload.get("revision_items"):
            return json.dumps({"questions": payload["revision_items"]}, ensure_ascii=False)
        if role == "入学诊断审核":
            questions = payload["generated_set"]["questions"]
            return json.dumps({
                "status": "approved",
                "decision_summary": "题量、来源、答案和画像难度均已逐题核对。",
                "items": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "approved",
                        "source_support": "supported",
                        "answer_consistency": "consistent",
                        "profile_fit": "fit",
                "knowledge_alignment": "aligned",
                "question_clarity": "self_contained",
                        "public_note": "来源与答案一致。",
                    }
                    for item in questions
                ],
            }, ensure_ascii=False)

        request = payload["request"]
        points = payload["target_knowledge_points"]
        sources = payload["authorized_sources"]
        question_types = [
            question_type
            for question_type, total in request["question_type_quotas"].items()
            for _ in range(total)
        ]
        questions = []
        coverage = {point["id"]: 0 for point in points}
        for index, question_type in enumerate(question_types):
            point = points[index % len(points)]
            source = next(item for item in sources if point["id"] in item["knowledge_point_ids"])
            common = {
                "item_id": f"Q{index + 1:02d}",
                "question_type": question_type,
                "prompt": f"第 {index + 1} 题：根据课程来源判断 {point['title']} 的适用边界。",
                "primary_knowledge_point_id": point["id"],
                "source_ref_id": source["source_ref_id"],
                "diagnostic_dimension": ("theory", "application", "engineering_judgment")[index % 3],
                "bloom_level": "apply" if index % 3 else "understand",
                "difficulty": 0.5,
                "explanation": f"依据 {source['location']} 的课程内容进行判断。",
            }
            if question_type == "true_false":
                common["answer"] = True
            elif question_type == "single_choice":
                common.update({"options": ["正确边界", "忽略来源", "跳过验证", "替换课程"], "answer": "A"})
            else:
                common.update({
                    "reference_answer": "说明输入、边界、验证方法和课程来源。",
                    "rubric": [
                        {"id": "scope", "label": "概念边界", "weight": 0.5},
                        {"id": "evidence", "label": "来源证据", "weight": 0.5},
                    ],
                })
            questions.append(common)
            coverage[point["id"]] += 1
        return json.dumps({
            "profile_adaptation_summary": "按当前画像的基础和目标设置中等难度并覆盖全部目标知识点。",
            "coverage_plan": [
                {"knowledge_point_id": point["id"], "question_count": coverage[point["id"]], "rationale": "覆盖当前课程起点。"}
                for point in points
            ],
            "questions": questions,
        }, ensure_ascii=False)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _learner(session):
    seed_competition_demo(session)
    # The historical demo's first reference is only a course objective. Supply
    # explanatory material in this isolated fixture so generation tests don't
    # depend on treating an empty post-filter excerpt as sufficient evidence.
    ref = session.get(DBSourceRef, "demo-ref-01")
    ref.quote += "\n\n## 闭环原理\n可信 RAG 将来源登记、解析、检索、生成和核验串联。检索召回不能保证回答受支持；生成后的主张需逐项核对引用，发现不一致再修订。"
    return session.query(DBUser).filter_by(username="lzz").one()


def _run_diagnostic(task_id, llm_factory, *, session_factory):
    from unittest.mock import patch
    from app.generation_dispatch import claim_resource_job, run_claimed_resource_job, _utcnow
    from app.database import DBGenerationTask
    with session_factory() as db:
        row = db.get(DBGenerationTask, task_id)
        if row.status in {'completed', 'cancelled'}:
            return
        row.next_attempt_at = _utcnow()
        db.commit()
        claim = claim_resource_job(db)
    assert claim and claim[0] == task_id
    with patch('app.diagnostic_api.build_diagnostic_llm', llm_factory):
        run_claimed_resource_job(*claim, session_factory=session_factory)


def test_diagnostic_task_restores_finished_result_without_repeating_generation():
    from sqlalchemy.orm import sessionmaker
    from app.diagnostic_tasks import queue_diagnostic_task, find_diagnostic_task
    engine, session = _session()
    try:
        learner = _learner(session)
        session.commit()
        request = DiagnosticBlueprintRequest(COURSE_ID, "recover-completed-paper", 15, "foundation")
        task = queue_diagnostic_task(session, user=learner, request=request)
        same = queue_diagnostic_task(session, user=learner, request=request)
        assert task['id'] == same['id'] and task['status'] == 'queued'
        backend = _DiagnosticLLM()
        factory = sessionmaker(bind=engine)
        _run_diagnostic(task['id'], lambda: backend, session_factory=factory)
        _run_diagnostic(task['id'], lambda: backend, session_factory=factory)
        session.expire_all()
        restored = find_diagnostic_task(session, user=learner, course_id=COURSE_ID,
                                        question_count=15, self_rating='foundation')
        assert restored['status'] == 'completed'
        assert len(restored['blueprint']['questions']) == 15
        assert backend.calls == ['入学诊断出题', '入学诊断审核']
        assert all(item['status'] == 'completed' for item in restored['generationStages'])
        assert queue_diagnostic_task(session, user=learner, request=request)['blueprint']['id'] == restored['blueprint']['id']
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_task_failure_is_retained_and_worker_resumes_without_resubmission(monkeypatch):
    from sqlalchemy.orm import sessionmaker
    import app.diagnostic_tasks as tasks
    from app.database import DBTaskEvent
    engine, session = _session()
    try:
        learner = _learner(session)
        session.commit()
        request = DiagnosticBlueprintRequest(COURSE_ID, "recover-failed-paper", 15, "foundation")
        task = tasks.queue_diagnostic_task(session, user=learner, request=request)
        original = tasks.generate_diagnostic_blueprint
        def fail(*args, **kwargs):
            raise DiagnosticGenerationError('diagnostic_model_generation_failed', '模型连接中断。')
        monkeypatch.setattr(tasks, 'generate_diagnostic_blueprint', fail)
        _run_diagnostic(task['id'], _DiagnosticLLM, session_factory=sessionmaker(bind=engine))
        session.expire_all()
        failed = tasks.get_diagnostic_task(session, task_id=task['id'], user=learner)
        assert failed['status'] == 'failed' and failed['blueprint'] is None
        assert tasks.get_diagnostic_task(session, task_id=task['id'], user=learner)['status'] == 'failed'
        monkeypatch.setattr(tasks, 'generate_diagnostic_blueprint', original)
        _run_diagnostic(task['id'], _DiagnosticLLM, session_factory=sessionmaker(bind=engine))
        session.expire_all()
        assert tasks.get_diagnostic_task(session, task_id=task['id'], user=learner)['status'] == 'completed'
        assert session.query(DBTaskEvent).filter_by(task_id=task['id'], event_type='learning_generation.failed').count() == 1
        assert session.query(DBTaskEvent).filter_by(task_id=task['id'], event_type='diagnostic.retry').count() == 0
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize('change_source', [False, True])
def test_failed_task_retry_restores_candidate_and_reviews_only_matching_evidence(monkeypatch, change_source):
    import app.diagnostic_generation as generation
    import app.diagnostic_tasks as tasks
    from app.database import DBTaskEvent
    original_batches = generation._diagnostic_review_batches
    monkeypatch.setattr(generation, '_diagnostic_review_batches',
        lambda generated, sources: original_batches(generated, sources, budget=1700))

    class InterruptedLLM(_DiagnosticLLM):
        async def generate(self, system_prompt, user_prompt, *, role):
            if role == '入学诊断审核':
                questions = json.loads(user_prompt)['generated_set']['questions']
                if any(item['item_id'] == 'Q15' for item in questions):
                    raise TimeoutError('synthetic unavailable review batch')
            return await super().generate(system_prompt, user_prompt, role=role)

    class ResumedLLM(_DiagnosticLLM):
        async def generate(self, system_prompt, user_prompt, *, role):
            if not change_source:
                assert role == '入学诊断审核', 'Already generated questions must survive a new execution.'
                assert any(item['item_id'] == 'Q15' for item in json.loads(user_prompt)['generated_set']['questions'])
            return await super().generate(system_prompt, user_prompt, role=role)

    engine, session = _session()
    try:
        learner = _learner(session)
        session.commit()
        request = DiagnosticBlueprintRequest(COURSE_ID, 'recover-saved-work', 15, 'foundation')
        task = tasks.queue_diagnostic_task(session, user=learner, request=request)
        factory = sessionmaker(bind=engine)
        first = InterruptedLLM()
        _run_diagnostic(task['id'], lambda: first, session_factory=factory)
        session.expire_all()
        failed = tasks.get_diagnostic_task(session, task_id=task['id'], user=learner)
        assert failed['status'] == 'failed' and failed['blueprint'] is None
        assert first.calls.count('入学诊断出题') == 1
        saved = session.query(DBTaskEvent).filter_by(task_id=task['id'], event_type='diagnostic.work_saved').all()
        candidate = next(item.payload for item in saved if item.payload['kind'] == 'candidate')
        old_call_id = candidate['call']['call_id']
        assert any(item.payload['kind'] == 'review_batch' for item in saved)
        assert 'reference_answer' not in json.dumps(failed)
        from app.m1_repository import M1Repository
        repository = M1Repository(session)
        public_task = repository.task_payload(repository.task(task['id']))
        assert all(item['event_type'] != 'diagnostic.work_saved' for item in public_task['events'])
        assert 'reference_answer' not in json.dumps(public_task)
        assert all(item['event_type'] != 'learning_generation.failed' for item in public_task['events'])
        if change_source:
            ref = session.get(DBSourceRef, 'demo-ref-01')
            ref.quote += '\n\n### 证据范围\n来源支持只针对明确的主张，不能从同主题就推出所有结论。'
            session.commit()
        # Retry through a new DB session and backend, without any scope cache.
        learner_id = learner.id
        session.close()
        session = factory()
        learner = session.get(DBUser, learner_id)
        resumed = ResumedLLM()
        _run_diagnostic(task['id'], lambda: resumed, session_factory=factory)
        session.expire_all()
        result = tasks.get_diagnostic_task(session, task_id=task['id'], user=learner)
        assert result['status'] == 'completed', result['message']
        row = session.get(DBDiagnosticBlueprint, result['blueprint']['id'])
        if change_source:
            assert resumed.calls.count('入学诊断出题') == 1
            assert row.review_decision['generationCallId'] != old_call_id
        else:
            assert resumed.calls == ['入学诊断审核']
            assert row.review_decision['generationCallId'] == old_call_id
            assert len(row.review_decision['itemReviews']) == 15
        assert session.query(DBTaskEvent).filter_by(task_id=task['id'], event_type='learning_generation.failed').count() == 1
    finally:
        session.close()
        engine.dispose()


def test_rejected_saved_candidate_is_revised_after_interrupted_request():
    import app.diagnostic_tasks as tasks
    from llm_client import ModelOutputLimitError

    class InterruptedRevisionLLM(_DiagnosticLLM):
        async def generate(self, system_prompt, user_prompt, *, role):
            payload = json.loads(user_prompt)
            if role == '入学诊断出题' and payload.get('revision_items'):
                raise ModelOutputLimitError('synthetic interrupted revision')
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == '入学诊断审核':
                result['status'] = 'rejected'
                result['items'][0].update(verdict='rejected', public_note='补充核对引用的步骤。')
            return json.dumps(result, ensure_ascii=False)

    class ResumeRevisionLLM(_DiagnosticLLM):
        async def generate(self, system_prompt, user_prompt, *, role):
            payload = json.loads(user_prompt)
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == '入学诊断出题':
                assert [item['item_id'] for item in payload['revision_items']] == ['Q01']
                assert '补充核对引用' in str(payload['previous_attempt_feedback'])
                result['questions'][0]['prompt'] += ' 请说明核对引用的步骤。'
            return json.dumps(result, ensure_ascii=False)

    engine, session = _session()
    try:
        learner = _learner(session)
        session.commit()
        request = DiagnosticBlueprintRequest(COURSE_ID, 'resume-rejected-candidate', 15, 'foundation')
        task = tasks.queue_diagnostic_task(session, user=learner, request=request)
        factory = sessionmaker(bind=engine)
        _run_diagnostic(task['id'], InterruptedRevisionLLM, session_factory=factory)
        session.expire_all()
        failed = tasks.get_diagnostic_task(session, task_id=task['id'], user=learner)
        assert failed['status'] == 'failed' and failed['blueprint'] is None
        resumed = ResumeRevisionLLM()
        _run_diagnostic(task['id'], lambda: resumed, session_factory=factory)
        session.expire_all()
        result = tasks.get_diagnostic_task(session, task_id=task['id'], user=learner)
        assert result['status'] == 'completed', result['message']
        assert resumed.calls == ['入学诊断出题', '入学诊断审核']
        row = session.get(DBDiagnosticBlueprint, result['blueprint']['id'])
        assert len(row.review_decision['generationCallIds']) == 2
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_restart_records_interruption_and_preserves_request():
    import app.diagnostic_tasks as tasks
    from app.database import DBGenerationTask
    engine, session = _session()
    try:
        learner = _learner(session)
        session.commit()
        request = DiagnosticBlueprintRequest(COURSE_ID, "recover-interrupted-paper", 15, "foundation")
        task = tasks.queue_diagnostic_task(session, user=learner, request=request)
        session.get(DBGenerationTask, task['id']).status = 'running'
        session.commit()
        assert tasks.recover_interrupted_diagnostics(session) == 0
        restored = tasks.find_diagnostic_task(session, user=learner, course_id=COURSE_ID,
                                              question_count=15, self_rating='foundation')
        assert restored['status'] == 'running' and restored['automation']['enabled']
        assert restored['request']['idempotency_key'] == request.idempotency_key
        assert tasks.recover_interrupted_diagnostics(session) == 0
    finally:
        session.close()
        engine.dispose()


def test_background_diagnostic_api_returns_task_before_model_work(monkeypatch):
    from fastapi import BackgroundTasks
    engine, session = _session()
    try:
        learner = _learner(session)
        session.commit()
        async def local_operation(operation):
            return operation(session)
        monkeypatch.setattr(diagnostic_api, 'run_db_op', local_operation)
        def must_not_generate_yet():
            raise AssertionError('Model work must run after the response')
        monkeypatch.setattr(diagnostic_api, 'build_diagnostic_llm', must_not_generate_yet)
        background = BackgroundTasks()
        response = asyncio.run(diagnostic_api.create_diagnostic_blueprint(
            DiagnosticGenerateRequest(course_id=COURSE_ID, idempotency_key='background-api-paper', background=True),
            current_user=learner, background_tasks=background))
        assert response['task']['status'] == 'queued' and response['blueprint'] is None
        assert len(background.tasks) == 0
        assert response['task']['automation']['state'] == 'queued'
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_task_lookup_accepts_browser_query_parameters(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    engine, session = _session()
    try:
        learner = _learner(session)
        session.commit()
        async def local_operation(operation):
            return operation(session)
        monkeypatch.setattr(diagnostic_api, 'run_db_op', local_operation)
        app = FastAPI()
        app.include_router(diagnostic_api.router)
        app.dependency_overrides[diagnostic_api.get_current_user] = lambda: learner
        with TestClient(app) as client:
            response = client.get('/api/v1/diagnostics/generation-tasks', params={
                'course_id': COURSE_ID, 'question_count': 15, 'self_rating': 'foundation'})
        assert response.status_code == 200, response.text
        assert response.json() == {'task': None}
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("field,value", [("knowledge_alignment", "misaligned"), ("question_clarity", "missing_context")])
def test_diagnostic_rejects_unrelated_topic_or_missing_question_context(field, value):
    class MisalignedLLM(_DiagnosticLLM):
        async def generate(self, system_prompt, user_prompt, *, role):
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == "入学诊断审核":
                assert json.loads(user_prompt)["target_knowledge_points"]
                result["items"][0][field] = value
                result["items"][0]["public_note"] = "题目未能直接检验对应知识点，或缺少作答所需条件。"
            return json.dumps(result, ensure_ascii=False)

    engine, session = _session()
    try:
        learner = _learner(session)
        with pytest.raises(DiagnosticGenerationError, match="题组审核未通过"):
            generate_diagnostic_blueprint(session, user=learner,
                request=DiagnosticBlueprintRequest(course_id=COURSE_ID, question_count=20, idempotency_key=f"review-{field}"),
                llm=MisalignedLLM())
        assert session.query(DBDiagnosticBlueprint).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_excerpt_keeps_late_topic_content_instead_of_document_prefix():
    from app.canonical_retrieval import teaching_excerpt
    unrelated = ("## GPU运行\nGPU操作默认异步执行，运行后需要同步检查。\n\n" * 600)
    relevant = "## 主成分分析与降维\n主成分分析使用正交投影保留方差；降维时按累计解释方差选择主成分数量。\n"
    text = unrelated + relevant * 4
    excerpt = teaching_excerpt(text, topics=["无监督学习、表示学习与降维"], max_chars=1800)
    assert len(text) > 12000
    assert "按累计解释方差选择主成分数量" in excerpt
    assert len(excerpt) <= 1800


def test_large_diagnostic_has_own_output_allowance_and_does_not_repeat_truncation():
    from llm_client import ModelOutputLimitError
    class TruncatedLLM(_DiagnosticLLM):
        max_tokens = 16384
        async def generate(self, system_prompt, user_prompt, *, role):
            self.calls.append(role)
            assert self.max_tokens == 32768
            raise ModelOutputLimitError("题组未写完")
    engine, session = _session()
    backend = TruncatedLLM()
    try:
        learner = _learner(session)
        with pytest.raises(DiagnosticGenerationError) as failure:
            generate_diagnostic_blueprint(session, user=learner,
                request=DiagnosticBlueprintRequest(course_id=COURSE_ID, question_count=25, idempotency_key="output-truncated-25"),
                llm=backend)
        assert failure.value.code == "diagnostic_output_limit"
        assert backend.calls == ["入学诊断出题"]
        assert backend.max_tokens == 16384
        assert session.query(DBDiagnosticBlueprint).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_review_output_budget_and_no_full_paper_regeneration_on_truncation():
    from llm_client import ModelOutputLimitError

    class ReviewTruncatedLLM(_DiagnosticLLM):
        max_tokens = 16384
        async def generate(self, system_prompt, user_prompt, *, role):
            if role == "入学诊断审核":
                self.calls.append(role)
                assert self.max_tokens >= 65536
                raise ModelOutputLimitError("核对未写完")
            return await super().generate(system_prompt, user_prompt, role=role)

    engine, session = _session()
    try:
        learner = _learner(session)
        backend = ReviewTruncatedLLM()
        with pytest.raises(DiagnosticGenerationError) as failure:
            generate_diagnostic_blueprint(session, user=learner,
                request=DiagnosticBlueprintRequest(COURSE_ID, "review-truncated", 15), llm=backend)
        assert failure.value.code == "diagnostic_review_output_limit"
        assert backend.calls == ["入学诊断出题", "入学诊断审核"]
        assert backend.max_tokens == 16384
        assert session.query(DBDiagnosticBlueprint).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_transient_review_failure_reuses_same_paper_and_positions():
    class RetryReviewLLM(_DiagnosticLLM):
        async def generate(self, system_prompt, user_prompt, *, role):
            payload = json.loads(user_prompt)
            if role == "入学诊断审核" and not hasattr(self, 'first_paper'):
                self.calls.append(role)
                self.first_paper = payload['generated_set']
                raise TimeoutError('synthetic review transport failure')
            if role == "入学诊断审核":
                assert payload['generated_set'] == self.first_paper
            return await super().generate(system_prompt, user_prompt, role=role)

    engine, session = _session()
    try:
        learner = _learner(session)
        backend = RetryReviewLLM()
        row, created = generate_diagnostic_blueprint(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, "review-transport-reuse", 15), llm=backend)
        assert created and row.status == 'ready'
        assert backend.calls == ["入学诊断出题", "入学诊断审核", "入学诊断审核"]
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_excerpt_uses_explanations_instead_of_unsolved_exercise_word_matches():
    from app.canonical_retrieval import teaching_excerpt
    explanation = '# 图结构\n## 信息传播\n图网络使用相邻节点的信息聚合形成当前节点表示。\n'
    exercise = '## 习题\n' + '图神经网络GraphSAGE GraphSAINT Cluster-GCN图训练：请比较采样粒度和偏差方差。\n' * 40
    source = explanation + exercise
    result = teaching_excerpt(source, topics=['图神经网络'], max_chars=800, prefer_explanations=True)
    assert '相邻节点的信息聚合' in result
    assert '请比较采样粒度' not in result
    assert 'GraphSAINT' not in result
    pdf_text = explanation + '\n\n--- 第276页 ---\n\n' + (
        '习题 9-13 面对大规模图，请比较GraphSAGE、GraphSAINT和Cluster-GCN。\n' * 35)
    pdf_result = teaching_excerpt(pdf_text, topics=['图神经网络'], max_chars=800, prefer_explanations=True)
    assert '相邻节点的信息聚合' in pdf_result
    assert 'GraphSAINT' not in pdf_result


def test_teaching_excerpt_preserves_operation_context_and_excludes_chapter_lists():
    from app.canonical_retrieval import teaching_excerpt
    source = ('# 教材\n## 数学介绍\n矩阵和向量是常见数据结构。\n'
        '# 数据预处理\n## 读取数据集\nCSV表格中NA表示缺失的数据。\n'
        '## 处理缺失值\n数值列可用训练样本的均值填补，验证数据只应用已有规则。\n'
        '## 转换\n类别特征转为数值后再输入模型。\n'
        '# 模型地图\n## 基础模型\n- 第 4 章 前馈网络\n- 第 9 章 图神经网络\n'
        '## 图神经网络教材\n<a href="https://example.test/book.pdf">下载 PDF</a>\n本书介绍图神经网络。\n')
    result = teaching_excerpt(source, topics=['数据集、特征工程与数据管道'], max_chars=900, prefer_explanations=True)
    assert 'CSV表格' in result and '验证数据只应用已有规则' in result and '类别特征' in result
    assert '第 9 章' not in result
    graph = teaching_excerpt(source, topics=['图神经网络'], max_chars=900, prefer_explanations=True)
    assert '下载 PDF' not in graph and '第 9 章' not in graph


def test_outline_only_point_blocks_before_spending_model_calls():
    engine, session = _session()
    try:
        learner = _learner(session)
        session.get(DBSourceRef, 'demo-ref-01').quote = '## 课程目标\n掌握可信RAG工程闭环。'
        backend = _DiagnosticLLM()
        preflight = diagnostic_preflight(session, user=learner, course_id=COURSE_ID, question_count=15)
        assert not preflight['canGenerate']
        with pytest.raises(DiagnosticGenerationError) as exc:
            generate_diagnostic_blueprint(session, user=learner,
                request=DiagnosticBlueprintRequest(COURSE_ID, 'outline-only-point', 15), llm=backend)
        assert exc.value.code == 'diagnostic_sources_insufficient' and not backend.calls
    finally:
        session.close()
        engine.dispose()


def test_chapter_table_and_nested_catalog_are_not_teaching_evidence():
    from app.canonical_retrieval import teaching_excerpt
    source = ('# 配套实践\n## 章节目录\n| 章 | 实践内容 |\n|---|---|\n'
        '| 6 | 循环神经网络、LSTM、梯度截断与变长序列 |\n'
        '### 循环神经网络\n[代码入口](chap6/)\n'
        '## 循环神经网络原理\n隐藏状态随时间递推，将上一步的信息与当前输入结合。\n'
        '| 方法 | 作用 |\n|---|---|\n| 梯度截断 | 将过大的梯度范数缩到阈值，限制更新步长 |\n')
    excerpt = teaching_excerpt(source, topics=['循环神经网络与序列建模'], max_chars=1200, prefer_explanations=True)
    assert '代码入口' not in excerpt and '| 6 |' not in excerpt
    assert '隐藏状态随时间递推' in excerpt and '限制更新步长' in excerpt
    assert teaching_excerpt('## 章节目录\n| 6 | 循环神经网络与序列建模 |',
        topics=['循环神经网络'], max_chars=1200, prefer_explanations=True) == ''


def test_batched_review_keeps_completed_batches_on_transport_retry(monkeypatch):
    import app.diagnostic_generation as generation
    from collections import Counter
    original_batches = generation._diagnostic_review_batches
    monkeypatch.setattr(generation, '_diagnostic_review_batches',
        lambda generated, sources: original_batches(generated, sources, budget=1700))

    class BatchLLM(_DiagnosticLLM):
        def __init__(self):
            super().__init__()
            self.batches = Counter()
            self.failed = None

        async def generate(self, system_prompt, user_prompt, *, role):
            if role == '入学诊断审核':
                payload = json.loads(user_prompt)
                questions = payload['generated_set']['questions']
                key = tuple(q['item_id'] for q in questions)
                self.batches[key] += 1
                assert len(payload['whole_paper_questions']) == 15
                assert {s['source_ref_id'] for s in payload['authorized_sources']} == {q['source_ref_id'] for q in questions}
                if len(self.batches) == 2 and self.failed is None:
                    self.failed = key
                    self.calls.append(role)
                    raise TimeoutError('synthetic second batch failure')
            return await super().generate(system_prompt, user_prompt, role=role)

    engine, session = _session()
    try:
        learner = _learner(session)
        backend = BatchLLM()
        row, created = generate_diagnostic_blueprint(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, 'review-batch-resume', 15), llm=backend)
        assert created and row.status == 'ready'
        assert backend.calls.count('入学诊断出题') == 1
        assert backend.batches[backend.failed] == 2
        assert all(count == 1 for key, count in backend.batches.items() if key != backend.failed)
        assert {item for batch in backend.batches for item in batch} == {f'Q{i:02d}' for i in range(1,16)}
        assert len(row.review_decision['reviewCallIds']) == len(backend.batches)
        assert len(row.review_decision['itemReviews']) == row.question_count
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize('failed_role', ['入学诊断出题', '入学诊断审核'])
@pytest.mark.parametrize('recover', [False, True])
def test_provider_connection_failure_is_not_teaching_feedback(failed_role, recover):
    import httpx

    class ConnectionLLM(_DiagnosticLLM):
        failures = 0
        attempts = 0

        async def generate(self, system_prompt, user_prompt, *, role):
            payload = json.loads(user_prompt)
            if role == '入学诊断出题':
                assert payload.get('previous_attempt_feedback') is None
            if role == failed_role:
                self.attempts += 1
                if not recover or self.failures == 0:
                    self.failures += 1
                    try:
                        raise httpx.ConnectError('synthetic private proxy address')
                    except httpx.ConnectError as exc:
                        # Same wrapper chain as the real backend retry helper.
                        raise RuntimeError('provider retries exhausted') from exc
            return await super().generate(system_prompt, user_prompt, role=role)

    engine, session = _session()
    try:
        learner = _learner(session)
        backend = ConnectionLLM()
        request = DiagnosticBlueprintRequest(COURSE_ID, 'connection-failure', 15)
        if recover:
            row, created = generate_diagnostic_blueprint(session, user=learner, request=request, llm=backend)
            assert created and row.status == 'ready'
            assert backend.attempts == 2
            assert backend.calls.count('入学诊断出题') == 1
        else:
            with pytest.raises(DiagnosticGenerationError) as error:
                generate_diagnostic_blueprint(session, user=learner, request=request, llm=backend)
            assert error.value.code == 'diagnostic_service_unavailable'
            assert error.value.status_code == 503
            assert '连接中断' in str(error.value)
            assert 'private proxy' not in str(error.value)
            assert '审核' not in str(error.value)
            assert backend.attempts == 3
            assert not session.query(DBDiagnosticBlueprint).filter_by(idempotency_key=request.idempotency_key).count()
            if failed_role == '入学诊断审核':
                assert backend.calls.count('入学诊断出题') == 1
    finally:
        session.close()
        engine.dispose()


def test_preflight_uses_profile_course_sources_and_exact_mixed_question_quota():
    engine, session = _session()
    try:
        learner = _learner(session)
        payload = diagnostic_preflight(
            session,
            user=learner,
            course_id=COURSE_ID,
            question_count=15,
        )
        assert payload["canGenerate"] is True
        assert payload["course"]["id"] == COURSE_ID
        assert payload["profileBasis"]["id"]
        assert payload["expectedQuestionCount"] == 15
        assert payload["estimatedMinutes"] == 30
        assert payload["coverage"]["sourceCount"] >= 4
        assert 3 <= len(payload["coverage"]["knowledgePoints"]) <= 15
        assert payload["coverage"]["questionTypes"] == {
            "true_false": 5,
            "single_choice": 5,
            "short_answer": 5,
        }
        assert payload["modelPolicy"] == {
            "model": "deepseek-v4-flash",
            "thinking": "enabled",
            "reasoningEffort": "max",
            "allowFallback": False,
        }
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_review_batches_overlap_but_publish_only_complete_reviews(monkeypatch):
    import app.diagnostic_generation as generation
    original_batches = generation._diagnostic_review_batches
    monkeypatch.setattr(generation, '_diagnostic_review_batches',
        lambda generated, sources: original_batches(generated, sources, budget=1700))

    class ConcurrentLLM(_DiagnosticLLM):
        def __init__(self):
            super().__init__()
            self.progress = {'active': 0, 'peak': 0, 'started': asyncio.Event()}

        async def generate(self, system_prompt, user_prompt, *, role):
            if role != '入学诊断审核':
                return await super().generate(system_prompt, user_prompt, role=role)
            self.progress['active'] += 1
            self.progress['peak'] = max(self.progress['peak'], self.progress['active'])
            if self.progress['active'] >= 2:
                self.progress['started'].set()
            try:
                await asyncio.wait_for(self.progress['started'].wait(), timeout=1)
                return await super().generate(system_prompt, user_prompt, role=role)
            finally:
                self.progress['active'] -= 1

    engine, session = _session()
    try:
        learner = _learner(session); backend = ConcurrentLLM()
        row, created = generate_diagnostic_blueprint(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, 'parallel-review-complete', 15), llm=backend)
        assert created and row.status == 'ready' and backend.progress['peak'] >= 2
        assert {item['item_id'] for item in row.review_decision['itemReviews']} == {f'Q{i:02d}' for i in range(1, 16)}
    finally:
        session.close(); engine.dispose()


def test_revising_one_item_reuses_approved_batches_and_stable_choices(monkeypatch):
    import app.diagnostic_generation as generation
    from collections import Counter
    original_batches = generation._diagnostic_review_batches
    monkeypatch.setattr(generation, '_diagnostic_review_batches',
        lambda generated, sources: original_batches(generated, sources, budget=1))

    class RevisionLLM(_DiagnosticLLM):
        def __init__(self):
            super().__init__()
            self.reviews = Counter()
            self.original_prompts = []
        async def generate(self, system_prompt, user_prompt, *, role):
            payload = json.loads(user_prompt)
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == '入学诊断出题' and not payload.get('revision_items'):
                self.original_prompts = [item['prompt'] for item in result['questions']]
            if role == '入学诊断出题' and payload.get('revision_items'):
                assert [item['item_id'] for item in payload['revision_items']] == ['Q15']
                assert len(payload['whole_paper_questions']) == 15
                result['questions'][-1]['prompt'] += ' 请解释如何核对引用。'
            if role == '入学诊断审核':
                item = payload['generated_set']['questions'][0]
                self.reviews[item['item_id']] += 1
                if item['item_id'] == 'Q15' and self.reviews['Q15'] == 1:
                    result['status'] = 'rejected'
                    result['items'][0].update(verdict='rejected', public_note='请说明引用核对条件。')
            return json.dumps(result, ensure_ascii=False)

    engine, session = _session()
    try:
        learner = _learner(session); backend = RevisionLLM()
        row, _ = generate_diagnostic_blueprint(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, 'one-item-revision', 15), llm=backend)
        assert row.status == 'ready' and backend.calls.count('入学诊断出题') == 2
        assert backend.reviews['Q15'] == 2
        assert all(count == 1 for key, count in backend.reviews.items() if key != 'Q15')
        assert len(row.review_decision['itemReviews']) == 15
        assert len(row.review_decision['generationCallIds']) == 2
        from app.database import DBAssessmentQuestionVersion
        saved_prompts = [session.get(DBAssessmentQuestionVersion, version_id).prompt for version_id in row.question_version_ids]
        assert saved_prompts[:14] == backend.original_prompts[:14]
        assert saved_prompts[-1] == backend.original_prompts[-1] + ' 请解释如何核对引用。'
    finally:
        session.close(); engine.dispose()


def test_long_correction_keeps_later_review_groups_reusable(monkeypatch):
    import app.diagnostic_generation as generation
    from collections import Counter
    original_batches = generation._diagnostic_review_batches
    monkeypatch.setattr(generation, '_diagnostic_review_batches',
        lambda generated, sources: original_batches(generated, sources, budget=6000))

    class GrowingRevisionLLM(_DiagnosticLLM):
        def __init__(self):
            super().__init__()
            self.reviews = Counter()
            self.groups = []
            self.revised = False

        async def generate(self, system_prompt, user_prompt, *, role):
            payload = json.loads(user_prompt)
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == '入学诊断出题' and payload.get('revision_items'):
                self.revised = True
                result['questions'][0]['prompt'] += ' 补充输入条件与核对步骤。' * 700
            if role == '入学诊断审核':
                ids = [item['item_id'] for item in payload['generated_set']['questions']]
                if not self.revised:
                    self.groups.append(ids)
                self.reviews.update(ids)
                if 'Q01' in ids and self.reviews['Q01'] == 1:
                    result['status'] = 'rejected'
                    next(item for item in result['items'] if item['item_id'] == 'Q01').update(
                        verdict='rejected', public_note='补充这道题的输入条件。')
            return json.dumps(result, ensure_ascii=False)

    engine, session = _session()
    try:
        learner = _learner(session); backend = GrowingRevisionLLM()
        row, _ = generate_diagnostic_blueprint(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, 'growing-revision', 15), llm=backend)
        assert row.status == 'ready' and len(backend.groups) > 1 and len(backend.groups[0]) > 1
        outside_changed_group = {item for group in backend.groups[1:] for item in group}
        assert all(backend.reviews[item] == 1 for item in outside_changed_group)
        assert backend.reviews['Q01'] == 2
        assert len(row.review_decision['itemReviews']) == 15
    finally:
        session.close(); engine.dispose()


def test_generation_is_idempotent_traceable_profile_adaptive_and_hides_answers():
    engine, session = _session()
    try:
        learner = _learner(session)
        profile = session.query(DBProfileSnapshot).filter_by(
            owner_public_id=learner.public_id,
        ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).first()
        legacy_quiz_count_before = session.query(DBQuizRecord).count()
        llm = _DiagnosticLLM()
        request = DiagnosticBlueprintRequest(COURSE_ID, "f3-diagnostic-idempotent-001", 15)
        first, created = generate_diagnostic_blueprint(session, user=learner, request=request, llm=llm)
        session.commit()
        replay, replay_created = generate_diagnostic_blueprint(session, user=learner, request=request, llm=llm)
        payload = diagnostic_blueprint_payload(session, first)

        assert created is True and replay_created is False
        assert replay.id == first.id
        assert session.query(DBDiagnosticBlueprint).count() == 1
        assert first.profile_snapshot_id == profile.id
        assert first.difficulty_bands["targetDifficulty"] == pytest.approx(0.511, abs=0.001)
        assert all(first.difficulty_bands["questionKinds"][kind] >= 1 for kind in (
            "theory", "application", "engineering_judgment",
        ))
        assert first.difficulty_bands["questionTypes"] == {
            "true_false": 5,
            "single_choice": 5,
            "short_answer": 5,
        }
        assert first.question_count == 15
        assert 3 <= len(first.knowledge_point_coverage) <= 15
        assert len(first.source_refs) >= 3
        assert [item["key"] for item in first.generation_stages] == ["analysis", "generation", "validation", "review"]
        assert first.review_decision["checks"]["answerKeyHidden"] == "passed"
        assert first.review_decision["model"] == "deepseek-v4-flash"
        assert llm.calls == ["入学诊断出题", "入学诊断审核"]
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        assert "answer_key" not in serialized and "scoring_rule" not in serialized
        assert "reference_answer" not in serialized
        assert set(item["diagnosticKind"] for item in payload["questions"]) == {
            "theory", "application", "engineering_judgment",
        }
        assert {item["questionType"] for item in payload["questions"]} == {
            "true_false", "single_choice", "short_answer",
        }
        assert session.query(DBQuizRecord).count() == legacy_quiz_count_before
    finally:
        session.close()
        engine.dispose()


def test_confirmed_conditions_and_preferences_reach_both_diagnostic_roles_and_frozen_context():
    from app.diagnostic_generation import _latest_profile

    class ContextLLM(_DiagnosticLLM):
        async def generate(self, system_prompt, user_prompt, *, role):
            context = json.loads(user_prompt)["profile"]
            registration = context["learning_adaptation"]["registration_profile"]
            assert "没有电脑" in registration["learning_context"]
            assert "20分钟" in registration["learning_context"]
            assert "均值" in registration["knowledge_base"]
            assert "先完整示范再独做" in str(registration["interaction_preferences"])
            assert "拟合越好" in str(context["confirmed_self_report"]["difficulty"])
            self.seen_context = context
            return await super().generate(system_prompt, user_prompt, role=role)

    engine, session = _session()
    try:
        learner = _learner(session)
        profile = _latest_profile(session, learner.public_id, COURSE_ID)
        profile.snapshot = {
            "course_context": {"courseId": COURSE_ID},
            "self_report": {
                "difficulty": {"summary": "我以为拟合越好就越可靠，待诊断。"},
                "preference": {"values": {"preference_context": "先完整示范再独做"}},
            },
            "profile_projection": {
                "knowledge_base": "能计算均值，概率未系统学习。",
                "learning_goals": ["理解模型为何不能只看训练误差"],
                "dimension_states": {"learning_context": {"summary": "没有电脑；安卓浏览器；每天20分钟，中文讲解"}},
            },
            "mastery_status": "awaiting_admission_assessment",
        }
        session.commit()
        backend = ContextLLM()
        row, _ = generate_diagnostic_blueprint(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, "context-complete", 15), llm=backend)
        frozen = row.review_decision["contextSnapshot"]["profile"]["learningContext"]
        assert frozen == backend.seen_context
        assert frozen["learning_adaptation"]["point_mastery"] is None
        assert backend.calls == ["入学诊断出题", "入学诊断审核"]
    finally:
        session.close()
        engine.dispose()


def test_new_choice_positions_are_reviewed_and_saved_with_matching_answers():
    from app.database import DBAssessmentQuestionVersion
    from collections import Counter

    class ChoiceLLM(_DiagnosticLLM):
        async def generate(self, system_prompt, user_prompt, *, role):
            if role == "入学诊断审核":
                questions = json.loads(user_prompt)["generated_set"]["questions"]
                choices = [q for q in questions if q["question_type"] == "single_choice"]
                assert set(q["answer"] for q in choices) == set("ABCD")
                for q in choices:
                    assert q["options"]["ABCD".index(q["answer"])] == "正确边界"
                    assert f"选项{q['answer']}正确" in q["explanation"]
                    assert "矩阵 A" in q["explanation"]
                self.reviewed = choices
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == "入学诊断出题":
                for q in result["questions"]:
                    if q["question_type"] == "single_choice":
                        q["options"] = [f"{label}. {text}" for label, text in zip("ABCD", q["options"])]
                        q["explanation"] = "选项A正确，说明适用边界；矩阵 A 是给定的数学变量。B选项错误，忽略来源。"
            return json.dumps(result, ensure_ascii=False)

    engine, session = _session()
    try:
        learner = _learner(session)
        backend = ChoiceLLM()
        row, _ = generate_diagnostic_blueprint(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, "choice-arrangement", 20), llm=backend)
        stored = {v.prompt: v for v in session.query(DBAssessmentQuestionVersion).filter(
            DBAssessmentQuestionVersion.id.in_(row.question_version_ids)).all()}
        for q in backend.reviewed:
            assert stored[q['prompt']].answer_key == {"choice": q['answer']}
            assert stored[q['prompt']].options == q['options']
            assert stored[q['prompt']].explanation == q['explanation']
        counts = Counter(q['answer'] for q in backend.reviewed)
        assert max(counts.values()) - min(counts.values()) <= 1
        before = diagnostic_blueprint_payload(session, row)
        again, created = generate_diagnostic_blueprint(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, "choice-arrangement", 20), llm=backend)
        assert not created and diagnostic_blueprint_payload(session, again) == before
        assert 'answer_key' not in json.dumps(before)
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_does_not_borrow_other_course_mastery():
    from app.diagnostic_generation import _latest_profile
    from datetime import datetime, timedelta

    engine, session = _session()
    try:
        learner = _learner(session)
        original = _latest_profile(session, learner.public_id, COURSE_ID)
        other = DBProfileSnapshot(owner_public_id=learner.public_id, profile_version="other",
            snapshot={"course_context": {"courseId": "other-course"}, "mastery": 1.0},
            content_hash="other", trace_id="other", created_at=datetime.now()+timedelta(seconds=30))
        session.add(other)
        session.commit()
        assert _latest_profile(session, learner.public_id, COURSE_ID).id == original.id
        # With only a different-course snapshot, new diagnosis requires the
        # learner's own confirmed starting information, not the foreign score.
        for row in session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).all():
            if row.id != other.id:
                session.delete(row)
        session.flush()
        assert _latest_profile(session, learner.public_id, COURSE_ID) is None
    finally:
        session.close()
        engine.dispose()


def test_multicourse_generation_supports_gateway_commits_and_preserves_ready_course():
    from app.multicourse_diagnostic import MultiCourseBlueprintRequest, generate_multicourse_blueprints
    from app.database import DBModelCall

    engine, session = _session()
    try:
        learner = _learner(session)
        llm = _DiagnosticLLM()
        request = MultiCourseBlueprintRequest((COURSE_ID, "missing-course"), "multi-audited-retry", 20)
        result = generate_multicourse_blueprints(session, user=learner, request=request, llm=llm)
        assert result["status"] == "partial"
        ready, failed = result["items"]
        assert ready["blueprint"]["questionCount"] == 20 and failed["status"] == "failed"
        assert llm.calls == ["入学诊断出题", "入学诊断审核"]
        assert session.query(DBModelCall).filter_by(status="completed").count() == 2
        session.rollback()
        assert session.get(DBDiagnosticBlueprint, ready["blueprint_id"]) is not None
        retry = generate_multicourse_blueprints(session, user=learner, request=request, llm=llm)
        assert retry["items"][0]["blueprint_id"] == ready["blueprint_id"]
        assert retry["items"][0]["created"] is False
        assert len(llm.calls) == 2
    finally:
        session.close()
        engine.dispose()


def test_missing_course_source_quotes_block_without_model_or_partial_blueprint():
    engine, session = _session()
    try:
        learner = _learner(session)
        for source in session.query(DBSourceRef).all():
            source.quote = ""
        session.commit()

        llm = _DiagnosticLLM()
        with pytest.raises(DiagnosticGenerationError) as blocked:
            generate_diagnostic_blueprint(
                session,
                user=learner,
                request=DiagnosticBlueprintRequest(COURSE_ID, "f3-diagnostic-filter-001", 15),
                llm=llm,
            )
        assert blocked.value.code == "diagnostic_sources_insufficient"
        assert llm.calls == []
        assert session.query(DBDiagnosticBlueprint).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_missing_profile_or_required_dimension_blocks_generation_with_recovery_reason():
    engine, session = _session()
    try:
        _learner(session)
        newcomer = DBUser(
            public_id="usr-f3-newcomer",
            username="f3-newcomer",
            hashed_password="not-used",
            role="student",
        )
        session.add(newcomer)
        session.commit()
        preflight = diagnostic_preflight(session, user=newcomer, course_id=COURSE_ID, question_count=15)
        assert preflight["canGenerate"] is False
        assert any("画像" in blocker for blocker in preflight["blockers"])
        with pytest.raises(DiagnosticGenerationError) as missing_profile:
            generate_diagnostic_blueprint(
                session,
                user=newcomer,
                request=DiagnosticBlueprintRequest(COURSE_ID, "f3-no-profile-001", 15),
                llm=_DiagnosticLLM(),
            )
        assert missing_profile.value.code == "diagnostic_profile_required"

        learner = session.query(DBUser).filter_by(username="lzz").one()
        for source in session.query(DBSourceRef).all():
            source.quote = ""
        session.commit()
        with pytest.raises(DiagnosticGenerationError) as missing_sources:
            generate_diagnostic_blueprint(
                session,
                user=learner,
                request=DiagnosticBlueprintRequest(COURSE_ID, "f3-no-theory-001", 15),
                llm=_DiagnosticLLM(),
            )
        assert missing_sources.value.code == "diagnostic_sources_insufficient"
    finally:
        session.close()
        engine.dispose()


def test_student_only_api_and_blueprint_owner_boundary(monkeypatch):
    engine, session = _session()
    try:
        learner = _learner(session)
        outsider = DBUser(
            public_id="usr-f3-outsider",
            username="f3-outsider",
            hashed_password="not-used",
            role="student",
        )
        teacher = DBUser(
            public_id="usr-f3-teacher",
            username="f3-teacher",
            hashed_password="not-used",
            role="teacher",
        )
        session.add_all([outsider, teacher])
        session.commit()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return await asyncio.to_thread(operation, session, *args, **kwargs)

        monkeypatch.setattr(diagnostic_api, "run_db_op", isolated_run_db_op)
        monkeypatch.setattr(diagnostic_api, "build_diagnostic_llm", _DiagnosticLLM)
        response = asyncio.run(diagnostic_api.create_diagnostic_blueprint(
            DiagnosticGenerateRequest(
                course_id=COURSE_ID,
                idempotency_key="f3-api-owner-001",
                question_count=15,
            ),
            current_user=learner,
        ))
        assert response["created"] is True
        blueprint_id = response["blueprint"]["id"]

        with pytest.raises(HTTPException) as forbidden_owner:
            asyncio.run(diagnostic_api.get_diagnostic_blueprint(blueprint_id, current_user=outsider))
        assert forbidden_owner.value.status_code == 403
        with pytest.raises(HTTPException) as forbidden_role:
            asyncio.run(diagnostic_api.create_diagnostic_blueprint(
                DiagnosticGenerateRequest(
                    course_id=COURSE_ID,
                    idempotency_key="f3-api-teacher-001",
                    question_count=15,
                ),
                current_user=teacher,
            ))
        assert forbidden_role.value.status_code == 403
    finally:
        session.close()
        engine.dispose()


def test_latest_migration_installs_diagnostic_blueprint_table():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE diagnostic_blueprints")
        migration = next(item for item in MIGRATIONS if item.version == "20260812_066")
        migration.apply(connection)
    assert "diagnostic_blueprints" in inspect(engine).get_table_names()
    engine.dispose()


def test_stage_diagnosis_keeps_course_endpoint_and_is_not_selected_by_occupation():
    from app.database import DBCourse, DBKnowledgePoint
    from app.diagnostic_scope import course_diagnostic_scope
    from types import SimpleNamespace
    engine, session = _session()
    try:
        learner = _learner(session)
        course = session.get(DBCourse, COURSE_ID)
        original = diagnostic_preflight(session, user=learner, course_id=COURSE_ID)
        points = original['coverage']['knowledgePoints']
        first, later = points[:4], points[4:]
        course.manifest_data = {**(course.manifest_data or {}), 'diagnostic_stages': [
            {'id': 'entry', 'title': '基础与当前目标', 'knowledge_point_codes': [p['id'] for p in first]},
            {'id': 'later', 'title': '后续综合任务', 'knowledge_point_codes': [p['id'] for p in later]},
        ]}
        session.flush()
        before = diagnostic_preflight(session, user=learner, course_id=COURSE_ID, self_rating='mastered')
        assert {p['id'] for p in before['coverage']['knowledgePoints']} == {p['id'] for p in first}
        assert len(before['assessmentScope']['courseKnowledgePoints']) == len(points)
        assert {p['id'] for p in before['assessmentScope']['deferredKnowledgePoints']} == {p['id'] for p in later}
        assert before['canGenerate'] and before['expectedQuestionCount'] == 15
        all_points = [session.get(DBKnowledgePoint, p['id']) for p in points]
        for background in ['数学博士，数学基础强', '教育从业者，未学微积分', '软件开发者，代码熟练']:
            profile = SimpleNamespace(snapshot={'foundation': background, 'mastery': 1})
            scope = course_diagnostic_scope(course, all_points, profile, question_count=25)
            assert scope['selected']['id'] == 'entry'
        # Only observations in this course justify suggesting the next stage.
        known = {p['id']: {'score': 0.9, 'evidence_item_count': 2} for p in first}
        profile = SimpleNamespace(snapshot={'course_id': COURSE_ID, 'mastery_by_knowledge_point': known})
        assert course_diagnostic_scope(course, all_points, profile, question_count=15)['selected']['id'] == 'later'
        profile.snapshot['course_id'] = 'different-course'
        assert course_diagnostic_scope(course, all_points, profile, question_count=15)['selected']['id'] == 'entry'
        after = diagnostic_preflight(session, user=learner, course_id=COURSE_ID, stage_id='later')
        assert {p['id'] for p in after['coverage']['knowledgePoints']} == {p['id'] for p in later}
        backend = _DiagnosticLLM()
        row, _ = generate_diagnostic_blueprint(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, 'stage-entry-generate', 15, 'foundation', 'entry'), llm=backend)
        payload = diagnostic_blueprint_payload(session, row)
        assert payload['coverageContract']['courseKnowledgePointCount'] == len(points)
        assert payload['assessmentScope']['selected']['id'] == 'entry'
        with pytest.raises(DiagnosticGenerationError, match='同一生成请求'):
            generate_diagnostic_blueprint(session, user=learner,
                request=DiagnosticBlueprintRequest(COURSE_ID, 'stage-entry-generate', 15, 'foundation', 'later'), llm=backend)
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_task_restore_is_bound_to_its_learning_stage():
    from app.database import DBCourse
    from app.diagnostic_tasks import queue_diagnostic_task, find_diagnostic_task
    engine, session = _session()
    try:
        learner = _learner(session)
        points = diagnostic_preflight(session, user=learner, course_id=COURSE_ID)['coverage']['knowledgePoints']
        course = session.get(DBCourse, COURSE_ID)
        course.manifest_data = {**(course.manifest_data or {}), 'diagnostic_stages': [
            {'id': 'entry', 'title': '初始阶段', 'knowledge_point_codes': [p['id'] for p in points[:4]]},
            {'id': 'later', 'title': '后续阶段', 'knowledge_point_codes': [p['id'] for p in points[4:]]},
        ]}
        first = queue_diagnostic_task(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, 'stage-task-entry', 15, 'foundation', 'entry'))
        second = queue_diagnostic_task(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, 'stage-task-later', 15, 'foundation', 'later'))
        assert first['id'] != second['id']
        for stage, expected in [('entry', first), ('later', second)]:
            restored = find_diagnostic_task(session, user=learner, course_id=COURSE_ID,
                question_count=15, self_rating='foundation', stage_id=stage)
            assert restored['id'] == expected['id']
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize('legacy', [False, True])
def test_default_stage_task_restores_from_explicit_browser_stage_without_new_generation(monkeypatch, legacy):
    import app.diagnostic_tasks as tasks
    from app.database import DBCourse, DBTaskEvent, DBGenerationTask
    engine, session = _session()
    try:
        learner = _learner(session)
        points = diagnostic_preflight(session, user=learner, course_id=COURSE_ID)['coverage']['knowledgePoints']
        course = session.get(DBCourse, COURSE_ID)
        course.manifest_data = {**(course.manifest_data or {}), 'diagnostic_stages': [
            {'id': 'entry', 'title': '初始阶段', 'knowledge_point_codes': [p['id'] for p in points[:4]]},
            {'id': 'later', 'title': '后续阶段', 'knowledge_point_codes': [p['id'] for p in points[4:]]},
        ]}
        request = DiagnosticBlueprintRequest(COURSE_ID, 'default-stage-paper', 15, 'foundation')
        first = tasks.queue_diagnostic_task(session, user=learner, request=request)
        if legacy:
            event = session.query(DBTaskEvent).filter_by(task_id=first['id'], event_type='diagnostic.request').one()
            event.payload = {key: value for key, value in event.payload.items() if key != 'resolvedStageId'}
            session.commit()
        assert tasks.queue_diagnostic_task(session, user=learner, request=request)['id'] == first['id']
        assert tasks.queue_diagnostic_task(session, user=learner, request=DiagnosticBlueprintRequest(
            COURSE_ID, 'default-stage-paper', 15, 'foundation', 'entry'))['id'] == first['id']
        with pytest.raises(DiagnosticGenerationError, match='诊断要求已改变'):
            tasks.queue_diagnostic_task(session, user=learner, request=DiagnosticBlueprintRequest(
                COURSE_ID, 'default-stage-paper', 15, 'foundation', 'later'))
        second = tasks.queue_diagnostic_task(session, user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, 'other-stage-paper', 15, 'foundation', 'later'))
        for stage in (None, 'entry'):
            restored = tasks.find_diagnostic_task(session, user=learner, course_id=COURSE_ID,
                question_count=15, self_rating='foundation', stage_id=stage)
            assert restored['id'] == first['id']
        assert tasks.find_diagnostic_task(session, user=learner, course_id=COURSE_ID,
            question_count=15, self_rating='foundation', stage_id='later')['id'] == second['id']
        assert session.query(DBGenerationTask).count() == 2
        backend = _DiagnosticLLM()
        _run_diagnostic(first['id'], lambda: backend, session_factory=sessionmaker(bind=engine))
        session.expire_all()
        done = tasks.get_diagnostic_task(session, user=learner, task_id=first['id'])
        assert done['status'] == 'completed', done['message']
        assert done['blueprint']['assessmentScope']['selected']['id'] == 'entry'
        assert backend.calls == ['入学诊断出题', '入学诊断审核']
        if legacy:
            # Also cover a historical completed task that predates stage freezing.
            for event in session.query(DBTaskEvent).filter_by(task_id=first['id'], event_type='diagnostic.request'):
                event.payload = {key: value for key, value in event.payload.items() if key != 'resolvedStageId'}
            session.commit()
        original = tasks.diagnostic_preflight
        def later_default(*args, **kwargs):
            return original(*args, **{**kwargs, 'stage_id': kwargs.get('stage_id') or 'later'})
        monkeypatch.setattr(tasks, 'diagnostic_preflight', later_default)
        assert tasks.find_diagnostic_task(session, user=learner, course_id=COURSE_ID,
            question_count=15, self_rating='foundation', stage_id='entry')['id'] == first['id']
        assert tasks.find_diagnostic_task(session, user=learner, course_id=COURSE_ID,
            question_count=15, self_rating='foundation')['id'] == second['id']
    finally:
        session.close()
        engine.dispose()


def test_curated_teaching_sections_preserve_subsections_and_ignore_code_headings():
    from app.canonical_retrieval import teaching_sections
    text = ('# 基础\n## 验证集\n验证用于选择候选。\n```python\n# 干扰标题\nx = 1\n```\n'
            '### 同一划分\n比较时保持数据相同。\n## 测试集\n测试用于最终评价。\n')
    chosen = teaching_sections(text, ['验证集'])
    assert '比较时保持数据相同' in chosen and '# 干扰标题' in chosen
    assert '测试用于最终评价' not in chosen
    assert teaching_sections(text, ['未存在章节']) == ''
