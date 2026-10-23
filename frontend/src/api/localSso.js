import { api, authConfig as config, request } from './common.js'

export const getLocalSsoWorkspace = (params = {}) =>
  request(api.get('/v1/local-sso/workspace', config(params)))

export const createLocalSsoProvider = (payload) =>
  request(api.post('/v1/local-sso/providers', payload, config()))

export const updateLocalSsoProviderStatus = (providerId, payload) =>
  request(api.post(`/v1/local-sso/providers/${encodeURIComponent(providerId)}/status`, payload, config()))

export const previewLocalSsoAssertion = (payload) =>
  request(api.post('/v1/local-sso/assertions/preview', payload, config()))

export const bindLocalSsoAssertion = (payload) =>
  request(api.post('/v1/local-sso/assertions/bind', payload, config()))

export const createLocalSsoSession = (payload) =>
  request(api.post('/v1/local-sso/sessions', payload, config()))

export const revokeLocalSsoMapping = (mappingId, organizationId) =>
  request(api.post(`/v1/local-sso/mappings/${encodeURIComponent(mappingId)}/revoke`, {
    organization_id: organizationId,
  }, config()))

export const createEmergencyAdminSession = (payload) =>
  request(api.post('/v1/local-sso/emergency-admin', payload, config()))
