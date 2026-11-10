export function quizStartQuestion(questions, requestedId = '') {
  return questions.find(question => question.id === requestedId)
    || questions.find(question => !question.attempts?.length)
    || questions.find(question => !question.attempts.some(attempt => attempt.correct))
    || questions[0]
    || null
}

export function quizStudySession(sessions, questions, activeIndex) {
  const index = sessions.findIndex(session => activeIndex + 1 >= session.startQuestion
    && activeIndex + 1 <= session.endQuestion)
  if (index < 0) return null
  const session = sessions[index]
  return {
    ...session,
    nextQuestion: sessions[index + 1]?.startQuestion || null,
    reachedEnd: activeIndex + 1 === session.endQuestion,
    attempted: questions.slice(session.startQuestion - 1, session.endQuestion)
      .every(question => question.attempts?.length),
  }
}
