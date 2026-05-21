import client from './client'

export const askQuestion = (question, maxCitations = 8) =>
  client.post('/api/qa/ask', { question, max_citations: maxCitations }).then(r => r.data)

export const traceAnswer = (answerId) =>
  client.get(`/api/qa/trace/${answerId}`).then(r => r.data)

export const suggestQuestions = (q) =>
  client.get('/api/qa/suggest', { params: { q } }).then(r => r.data)
