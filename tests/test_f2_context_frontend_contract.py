from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_SERVICE = ROOT / "frontend" / "src" / "services" / "context.js"
CONTEXT_RECOVERY_VIEW = ROOT / "frontend" / "src" / "views" / "ContextRecovery.vue"


def _run_context_service_contract() -> dict:
    script = r"""
import fs from 'node:fs'

const servicePath = process.argv[1]
let source = fs.readFileSync(servicePath, 'utf8')
source = source.replace(
  /import \{ api, buildHeaders \} from '\.\.\/api'\s*/,
  "const api = {}; const buildHeaders = () => ({});\n",
)

const storage = new Map()
globalThis.localStorage = {
  getItem(key) { return storage.has(key) ? storage.get(key) : null },
  setItem(key, value) { storage.set(key, String(value)) },
  removeItem(key) { storage.delete(key) },
}

const encoded = Buffer.from(source, 'utf8').toString('base64')
const module = await import(`data:text/javascript;base64,${encoded}`)

module.saveStoredContext({
  userId: 'user-a',
  courseId: 'course-a',
  chapterId: 'chapter-a',
  knowledgePointId: 'kp-a',
  taskId: 'task-a',
  resourceId: 'resource-a',
  sourceRefId: 'source-a',
  attemptId: 'attempt-a',
  version: 'ctx-a',
})

const switched = module.contextRefFromRoute({
  params: { courseId: 'course-b' },
  query: { knowledge_point_id: 'kp-b' },
})
const unchanged = module.contextRefFromRoute({ params: {}, query: {} })

process.stdout.write(JSON.stringify({
  switched,
  unchanged,
  plain401Detail: module.contextErrorDetail({
    response: { status: 401, data: { detail: 'Unauthorized' } },
  }),
  structuredDetail: module.contextErrorDetail({
    response: { data: { detail: { code: 'context_forbidden', message: 'denied' } } },
  }),
  plain401IsContext: module.isContextResolutionError({ response: { status: 401 } }),
  explicitContextIsContext: module.isContextResolutionError({
    contextDetail: { code: 'context_forbidden' },
  }),
}))
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(CONTEXT_SERVICE)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def test_course_switch_drops_stale_descendants_before_applying_deep_link_ids():
    payload = _run_context_service_contract()
    switched = payload["switched"]

    assert switched == {
        "userId": "user-a",
        "courseId": "course-b",
        "chapterId": None,
        "knowledgePointId": "kp-b",
        "taskId": None,
        "resourceId": None,
        "sourceRefId": None,
        "attemptId": None,
        "version": None,
    }


def test_same_course_restore_keeps_saved_context_and_only_explicit_context_errors_redirect():
    payload = _run_context_service_contract()

    assert payload["unchanged"] == {
        "userId": "user-a",
        "courseId": "course-a",
        "chapterId": "chapter-a",
        "knowledgePointId": "kp-a",
        "taskId": "task-a",
        "resourceId": "resource-a",
        "sourceRefId": "source-a",
        "attemptId": "attempt-a",
        "version": "ctx-a",
    }
    assert payload["plain401IsContext"] is False
    assert payload["explicitContextIsContext"] is True
    assert payload["plain401Detail"] is None
    assert payload["structuredDetail"] == {
        "code": "context_forbidden",
        "message": "denied",
        "field": None,
    }


def test_context_recovery_safe_exit_cannot_reopen_the_failed_route():
    source = CONTEXT_RECOVERY_VIEW.read_text(encoding="utf-8")

    assert "返回首页" in source
    assert "context.clear({ keepCourse: false })" in source
    assert "router.push('/')" in source
    assert "返回原页面" not in source
    assert "route.query.return_to" not in source
