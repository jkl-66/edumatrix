import { api, authConfig as config, request } from './common.js'

export function getM7IntegrationWorkspace(params = {}) {
  return request(api.get('/v1/m7/integrations/workspace', config(params)))
}

export function enqueueM7Delivery(payload) {
  return request(api.post('/v1/m7/integrations/deliveries', payload, config()))
}

export function attemptM7Delivery(deliveryId, outcome) {
  return request(api.post(`/v1/m7/integrations/deliveries/${encodeURIComponent(deliveryId)}/attempt`, {
    outcome,
    error_code: outcome === 'failure' ? 'mock_lrs_unavailable' : '',
  }, config()))
}

export function deliverM7ToLocalLrs(deliveryId) {
  return request(api.post(`/v1/m7/integrations/deliveries/${encodeURIComponent(deliveryId)}/local-lrs`, {}, config()))
}

export function requeueM7Delivery(deliveryId) {
  return request(api.post(`/v1/m7/integrations/deliveries/${encodeURIComponent(deliveryId)}/requeue`, {}, config()))
}

export function launchM7Cmi5Session(payload) {
  return request(api.post('/v1/m7/integrations/cmi5/sessions', payload, config()))
}

export function transitionM7Cmi5Session(sessionId, payload) {
  return request(api.post(`/v1/m7/integrations/cmi5/sessions/${encodeURIComponent(sessionId)}/transition`, payload, config()))
}

export function getLocalWebhookWorkspace(organizationId) {
  return request(api.get('/v1/local-webhooks/workspace', config({ organization_id: organizationId })))
}

export function createLocalWebhookEndpoint(payload) {
  return request(api.post('/v1/local-webhooks/endpoints', payload, config()))
}

export function createLocalWebhookEvent(payload) {
  return request(api.post('/v1/local-webhooks/events', payload, config()))
}

export function enqueueLocalWebhookEvent(payload) {
  return request(api.post('/v1/local-webhooks/deliveries', payload, config()))
}

export function sendLocalWebhookDelivery(deliveryId, fault = 'none') {
  return request(api.post(`/v1/local-webhooks/deliveries/${encodeURIComponent(deliveryId)}/send`, { fault }, config()))
}
