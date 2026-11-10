"""Teaching constraints reflect the installed runtime, without executing models."""
from app.teaching_runtime import teaching_runtime_context
from app.resource_bundles import _resource_runtime_context
from app.path_draft import _path_model_context, _course_facts, _path_learning_snapshot
from types import SimpleNamespace
from tests.test_path_teaching_units import case


def test_paths_and_resources_share_runtime_and_data_conditions(case, monkeypatch):
    monkeypatch.setattr('app.code_sandbox.CODE_SANDBOX_EXECUTOR', SimpleNamespace(enabled=False))
    db, user, course, profile, *_ = case
    snapshot = _path_learning_snapshot(db, user=user, course_id=course.id, profile=profile, use_current=False)
    context = _path_model_context(_course_facts(db, course_id=course.id), course=course,
                                  profile=profile, snapshot=snapshot, time_budget_minutes=40)
    assert context['runtime'] == _resource_runtime_context() == teaching_runtime_context()
    assert context['runtime']['networkAvailable'] is False
    assert context['runtime']['scope'] == 'product_code_sandbox'
    assert '不代表学习者的浏览器' in context['runtime']['scopeDescription']
    assert context['runtime']['fileAccessAvailable'] is False
    assert 'torch' in context['runtime']['supportedModules']
    assert 'io' in context['runtime']['supportedModules']
    assert 'io.BytesIO' in context['runtime']['datasetPolicy']
    assert 'tensorflow' not in context['runtime']['supportedModules']
    assert context['runtime']['executionEnabled'] is False  # isolated test mode
    assert '日志' in context['runtime']['planningPolicy']


def test_planning_reflects_configured_runtime_instead_of_old_ten_second_cap(monkeypatch):
    monkeypatch.setattr('config.CONFIG', SimpleNamespace(sandbox_timeout=45))
    assert teaching_runtime_context()['timeoutSeconds'] == 45
