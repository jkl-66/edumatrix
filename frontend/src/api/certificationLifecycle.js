import {api,buildHeaders,normalizeApiError} from './common'
const config=params=>({headers:buildHeaders(),params});async function req(p){try{return(await p).data}catch(e){throw normalizeApiError(e)}}
export const getCertificationLifecycle=organizationId=>req(api.get('/v1/certification-lifecycle/workspace',config({organization_id:organizationId})))
export const scanCertifications=(organizationId,upcomingDays=30)=>req(api.post('/v1/certification-lifecycle/scan',{organization_id:organizationId,upcoming_days:upcomingDays},config()))
export const revokeCertification=(id,payload)=>req(api.post(`/v1/certification-lifecycle/certifications/${encodeURIComponent(id)}/revoke`,payload,config()))
export const readCertificationNotice=id=>req(api.post(`/v1/certification-lifecycle/notifications/${encodeURIComponent(id)}/read`,{},config()))
