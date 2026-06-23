import { defineStore } from 'pinia'
import { generateQuiz, evaluateQuizAnswer, adaptQuiz } from '../api'

export const useQuizStore = defineStore('quiz', {
  state: () => ({
    quizState: 'idle', // idle | generating | answering | evaluating | adapting
    quizData: null,
    quizAnswer: '',
    quizConfidence: parseInt(localStorage.getItem('edumatrix_quiz_confidence') || '5', 10),
    quizResult: null,
    quizAttempt: 1,
    quizConcept: '',
    quizSessionId: '',
  }),
  actions: {
    setConfidence(v) {
      this.quizConfidence = v
      try {
        localStorage.setItem('edumatrix_quiz_confidence', String(v))
      } catch (e) {
        console.error('Failed to save quiz confidence:', e)
      }
    },
    resetQuiz() {
      this.quizState = 'idle'
      this.quizData = null
      this.quizResult = null
      this.quizAnswer = ''
      this.quizConcept = ''
      this.quizSessionId = ''
      this.quizAttempt = 1
    },
    async startQuizAction(studentId, conceptName) {
      if (!conceptName || !conceptName.trim()) return
      this.quizConcept = conceptName.trim()
      this.quizState = 'generating'
      this.quizResult = null
      this.quizAnswer = ''
      this.quizConfidence = 5
      this.quizAttempt = 1
      this.quizSessionId = 'session-' + Date.now()

      try {
        const data = await generateQuiz(studentId, this.quizConcept, 'medium', this.quizSessionId)
        this.quizData = data
        this.quizState = 'answering'
      } catch (e) {
        console.error('Failed to generate quiz:', e)
        this.quizData = { question: `请解释 ${this.quizConcept} 的核心概念`, hints: ['想想基本定义'] }
        this.quizState = 'answering'
      }
    },
    async submitQuizAnswerAction(studentId) {
      if (!this.quizAnswer || !this.quizAnswer.trim() || !this.quizData) return
      this.quizState = 'evaluating'

      try {
        const result = await evaluateQuizAnswer(
          this.quizData.quiz_id, studentId,
          this.quizAnswer.trim(), this.quizConfidence / 10, this.quizAttempt
        )
        this.quizResult = result
        this.quizState = 'adapting'
      } catch (e) {
        console.error('Failed to evaluate quiz answer:', e)
        this.quizResult = {
          accuracy_score: 0.5,
          ai_confidence: 0.6,
          feedback: '评估出错，请重试',
          next_action: 'practice',
          concept_mastery_updated: 0.5,
          confidence_calibration: 0.2,
        }
        this.quizState = 'adapting'
      }
    },
    async continueQuizAction(studentId) {
      if (!this.quizData || !this.quizResult) return
      this.quizState = 'generating'
      this.quizAttempt++

      try {
        const data = await adaptQuiz(
          studentId,
          this.quizData.quiz_id,
          this.quizResult.next_action,
          this.quizData.concept,
          this.quizAttempt,
          this.quizSessionId
        )
        this.quizData = data
        this.quizAnswer = ''
        this.quizConfidence = 5
        this.quizResult = null
        this.quizState = 'answering'
      } catch (e) {
        console.error('Failed to adapt quiz:', e)
        this.quizState = 'answering'
      }
    }
  }
})
