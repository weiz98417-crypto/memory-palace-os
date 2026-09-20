export function buildIntegrationView(payload: Record<string, any>) {
  const identities = Array.isArray(payload.identities) ? payload.identities : []
  return {
    identities,
    channel: 'WECOM_SIMULATOR_OUTBOX',
    productionDeliveryClaim: false,
  }
}