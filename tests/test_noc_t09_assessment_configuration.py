from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
UTILITY = ROOT / "frontend/src/utils/assessmentConfiguration.js"
VIEW = ROOT / "frontend/src/views/FormalExamWorkspace.vue"


def run_node(expression: str) -> str:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", expression],
        cwd=ROOT / "frontend",
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_assessment_configuration_helpers_cover_duration_today_sort_and_course_options():
    output = run_node(
        """
        import {
          calculateAssessmentDuration,
          courseOptionsFromShelf,
          sortKnowledgePoints,
          todayKnowledgePointIds,
        } from './src/utils/assessmentConfiguration.js';
        const payload = {
          shelf: [{id: 'course-a', title: '课程 A'}],
          recommendations: [{id: 'course-a', title: '重复'}, {id: 'course-b', title: '课程 B'}],
        };
        const points = [{id: 'kp-b', title: '乙'}, {id: 'kp-a', title: '甲'}];
        console.log(JSON.stringify({
          duration: calculateAssessmentDuration({single_choice: 2, multiple_choice: 1, short_answer: 1}),
          courses: courseOptionsFromShelf(payload).map(item => item.id),
          today: todayKnowledgePointIds([
            {course_id: 'course-a', knowledge_point_id: 'kp-a'},
            {course_id: 'course-b', knowledge_point_id: 'kp-b'},
          ], 'course-a'),
          sorted: sortKnowledgePoints(points, ['kp-a']).map(item => item.id),
          minimum: calculateAssessmentDuration({}),
        }));
        """,
    )
    assert output == '{"duration":9,"courses":["course-a","course-b"],"today":["kp-a"],"sorted":["kp-a","kp-b"],"minimum":5}'


def test_formal_exam_view_contract_has_in_page_course_selection_and_generation_stage():
    source = VIEW.read_text(encoding="utf-8")
    assert "listKnowledgeCourseShelf" in source
    assert "courseOptionsFromShelf" in source
    assert "getM5TodayWork" in source
    assert "todayKnowledgePointIds" in source
    assert "sortKnowledgePoints" in source
    assert "今日待测试" in source
    assert "calculateAssessmentDuration" in source
    assert "generationStatus" in source
    assert "generationStatus.value = 'generating'" in source
    assert "generationStatus.value = 'error'" in source
    assert 'data-testid="exam-generation-waiting"' in source
    assert "loadTodayWork" in source
    assert "watch(courseId" in source
    assert "resetLearnerConfiguration" in source
    assert "{{ computedDurationMinutes }} 分钟" in source
    assert "busy.value" in source and "router.replace({ path: '/workspace/assessment/exams', query })" in source
    assert "router.push('/knowledge')" not in source
    assert "liveGenerationEnabled" in source
    assert "if (liveGenerationEnabled.value) return 50" in source
    assert "大模型生成 · 题库现有" in source
    assert "无可用模型 · 题库现有" in source


def test_assessment_configuration_utility_is_small_and_has_no_network_or_storage_side_effects():
    source = UTILITY.read_text(encoding="utf-8")
    assert "axios" not in source
    assert "localStorage" not in source
    assert "fetch(" not in source
