export function buildFieldView(snapshot: Record<string, any>) {
  const incident = Array.isArray(snapshot.incidents) ? snapshot.incidents[0] : null
  const advice = incident?.advice || snapshot.advice || null
  const evidenceStatus = advice?.evidence_status || null
  const text = evidenceStatus === 'NO_EVIDENCE'
    ? '没有依据'
    : advice?.advice || '建议正在生成。'
  return {
    tasks: Array.isArray(incident?.tasks) ? incident.tasks : [],
    evidence: Array.isArray(incident?.evidence) ? incident.evidence : [],
    advice: advice ? {
      status: String(advice.status || 'PENDING'),
      evidenceStatus,
      text,
      readOnly: true,
    } : null,
  }
}