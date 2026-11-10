import test from 'node:test'
import assert from 'node:assert/strict'
import { trainingTaskPresentation, trainingReportTemplate } from '../src/utils/trainingTaskPresentation.js'

test('legacy answer copies do not prefill an independent learning report', () => {
  const answer = '预测目标是是否续报，输入为学习分钟数、作业次数和是否通过。'
  const instruction = '根据表N的预测时点，说明目标、标签和输入，并解释理由。'
  const task = {
    steps: [{ id: 'step-6', title: '独立判断', instruction, expectedResult: answer }],
    checkpoints: [{ id: 'check-6', afterStepId: 'step-6', verification: answer, passCondition: answer }],
    deliverables: [{ id: 'deliverable-6', title: '独立判断', description: answer, format: '文字' }],
    rubric: [{ id: 'rubric-6', criterion: '独立判断', evidence: answer, points: 100 }],
  }
  const original = structuredClone(task)
  const presented = trainingTaskPresentation(task)
  assert.equal(presented.deliverables[0].description, instruction)
  assert.equal(presented.rubric[0].evidence, instruction)
  assert.equal(presented.checkpoints[0].verification, instruction)
  assert.equal(presented.checkpoints[0].passCondition, answer)
  assert.deepEqual(task, original)
  const report = trainingReportTemplate('角色判断', task, [{ title: '阈值实验', completed: false }])
  assert.ok(report.includes(instruction))
  assert.ok(report.includes('阈值实验：待完成'))
  assert.ok(report.includes('我的记录：'))
  assert.ok(!report.includes(answer))
})

test('authored submission requirements and scoring points remain intact', () => {
  const task = {
    steps: [{ instruction: '记录输出。', expectedResult: '2/4/5' }],
    checkpoints: [{ verification: '比较实际输出。', passCondition: '三项计数一致。' }],
    deliverables: [{ title: '运行记录', description: '提供程序输出及解释。' }],
    rubric: [{ evidence: '说明阈值改变了哪些行。', points: 100 }],
  }
  assert.deepEqual(trainingTaskPresentation(task), task)
  assert.ok(trainingReportTemplate('实验', task).includes('提供程序输出及解释。'))
  assert.ok(!trainingReportTemplate('实验', task).includes('2/4/5'))
})

test('repeated expected values keep the corresponding step requirement', () => {
  const task = {
    steps: [
      { id: 'first', title: '第一组', instruction: '算第一组。', expectedResult: '5' },
      { id: 'second', title: '第二组', instruction: '算第二组。', expectedResult: '5' },
    ],
    checkpoints: [{ afterStepId: 'second', verification: '5' }],
    deliverables: [{ title: '第二组', description: '5' }],
    rubric: [{ criterion: '第一组', evidence: '5' }],
  }
  const shown = trainingTaskPresentation(task)
  assert.equal(shown.checkpoints[0].verification, '算第二组。')
  assert.equal(shown.deliverables[0].description, '算第二组。')
  assert.equal(shown.rubric[0].evidence, '算第一组。')
})
