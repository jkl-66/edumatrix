import assert from 'node:assert/strict'
import test from 'node:test'
import { displayLabel, learningText, referenceTitle, recordFacts, teachingText } from '../src/utils/learningCopy.js'
import { translateError } from '../src/services/errorTranslator.js'

test('invalid learning content is not described as another editor changing it', () => {
  const invalid = translateError({ status: 409, detail: { code: 'handout_content_incomplete', message: 'structured handout is missing required learning sections' } }).message
  assert.ok(invalid.includes('补全讲义标题'))
  assert.ok(!invalid.includes('别处'))
  const conflict = translateError({ status: 409, detail: { code: 'resource_version_conflict' } }).message
  assert.ok(conflict.includes('别处更新'))
})
import { EduMatrixApiError, errorMessageText } from '../src/api/common.js'

test('old assessment metadata becomes readable feedback without changing the outcome', () => {
  const names = { 'kp-list-index': '列表索引', 'ref-python-guide': 'Python 入门讲义' }
  const text = learningText('correct=false；grading_status=graded。建议复习 kp-list-index，参考 ref-python-guide。', '', names)
  assert.equal(text, '本题尚未答对；已完成评分。建议复习 列表索引，参考 Python 入门讲义。')
  assert.equal(learningText('correct=null'), '本题尚未完成评分')
  assert.equal(learningText('correct=true'), '本题回答正确')
  assert.equal(displayLabel('failed'), '未完成，请重试')
  assert.equal(displayLabel('new_unknown_state'), '暂未说明')
})

test('display helpers keep original records and educational text intact', () => {
  const item = { id: 'kp-list-index', title: '列表索引', status: 'pending' }
  const original = structuredClone(item)
  assert.equal(referenceTitle(item), '列表索引')
  assert.equal(learningText('Python 列表从 0 开始。得分 60%，请再检查索引范围。'), 'Python 列表从 0 开始。得分 60%，请再检查索引范围。')
  assert.deepEqual(item, original)
  assert.equal(learningText({ secret_key: 'not-displayable' }, '暂时没有点评'), '暂时没有点评')
  assert.equal(learningText('材料“Python基础 · video”的标题'), '材料“Python基础 · 学习视频”的标题')
  assert.equal(learningText('教学代码 `name = "topic · video"`'), '教学代码 `name = "topic · video"`')
})

test('claim reviews translate protocol states while preserving teaching code', () => {
  assert.equal(learningText('来源支持为 unsupported；计算正确。'), '课程材料未直接说明这一点；计算正确。')
  assert.equal(learningText('判定为 contradicted，而非 supported。'), '判定为 与参考资料不一致，而非 有资料支持。')
  assert.equal(learningText('示例 `support = "unsupported"`。'), '示例 `support = "unsupported"`。')
})

test('teaching calls, containers and Markdown code survive feedback wording cleanup', () => {
  const code = '```python\nmodel = LinearRegression()\nvalues = []\nif not values:\n    status = "pending"\n    correct = False\n    print("ref-example")\n```'
  const text = `correct=false。\n\n${code}\n\n再运行 \`model.predict()\` 核对结果。`
  assert.equal(learningText(text), text.replace('correct=false', '本题尚未答对'))
  assert.equal(learningText('写 model = LinearRegression()，再初始化 values = []。'), '写 model = LinearRegression()，再初始化 values = []。')
  const tildeCode = '~~~python\nprint("correct=true")\n~~~'
  assert.equal(learningText(tildeCode), tildeCode)
})

test('teaching explanations remove explicit metadata without rewriting their content', () => {
  const teaching = '证据不足不能说明原假设为假。画像快照与课程来源是本题术语。\n\n计算值123456789012345678901234。\n\n'
    + '```python\ntrace_id = "trace-example"\nif True:\n    print(trace_id)\n```\n\n'
    + '公式 $trace_id=1$ 与行内代码 `trace_id="trace-example"` 保留。'
  assert.equal(teachingText(teaching), teaching)
  assert.equal(teachingText(teaching + '\ntrace_id=trace-internal-12345678'), teaching + '\n')
  assert.equal(teachingText('"trace_id": "trace-internal"', '暂无解析'), '暂无解析')
  assert.equal(teachingText('correct=false；grading_status=graded。'), '本题尚未答对；已完成评分。')
})

test('API errors retain structured diagnostics while exposing actionable messages', () => {
  const detail = { code: 'diagnostic_generation_model_policy_invalid', message: '诊断必须使用 model-x / reasoning max' }
  const error = new EduMatrixApiError(503, detail)
  assert.equal(error.detail, detail)
  assert.equal(error.status, 503)
  assert.match(error.message, /联系管理员检查服务设置/)
  assert.doesNotMatch(error.message, /reasoning|model-x|503/)
  assert.equal(errorMessageText([{ msg: '请选择课程' }, { msg: '请填写学习目标' }]), '请选择课程；请填写学习目标')
  assert.equal(translateError({ status: 401, detail: 'Unauthorized' }).message, '登录状态已失效，请重新登录。')
  for (const raw of ['HTTP 500 Internal Server Error', '解析失败：Traceback sqlite failure', { code: 'unknown_internal_error' }, null]) {
    const message = translateError(raw).message
    assert.ok(message)
    assert.doesNotMatch(message, /Traceback|sqlite|HTTP|500|unknown_internal_error|\[object Object\]/)
  }
})

test('administrative summaries preserve negative results and hide internal fields', () => {
  assert.deepEqual(recordFacts({accepted: false, status: 'failed', trace_id: 'trace-private'}), ['未完成，请重试', '未接收本次记录'])
  assert.deepEqual(recordFacts({active_members: 0, content_hash: 'secret'}), ['当前成员：0'])
})
