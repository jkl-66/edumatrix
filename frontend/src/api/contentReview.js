import { api, buildHeaders, normalizeApiError } from './common'
const config=()=>({headers:buildHeaders()})
async function request(p){try{return(await p).data}catch(error){throw normalizeApiError(error)}}
export const getContentReviewQueue=status=>request(api.get('/v1/content-review/queue',{...config(),params:status?{status_filter:status}:{}}))
export const getContentReviewCase=id=>request(api.get(`/v1/content-review/cases/${encodeURIComponent(id)}`,config()))
export const submitContentReview=payload=>request(api.post('/v1/content-review/cases',payload,config()))
export const decideContentReview=(id,payload)=>request(api.post(`/v1/content-review/cases/${encodeURIComponent(id)}/decisions`,payload,config()))
