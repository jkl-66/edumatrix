import { api, buildHeaders, normalizeApiError } from './common'
const config=params=>({headers:buildHeaders(),params})
async function request(p){try{return(await p).data}catch(error){throw normalizeApiError(error)}}
export const getModelOperationsDashboard=(days=7)=>request(api.get('/v1/model-operations-dashboard',config({days})))
export async function downloadModelOperations(format,days=7){
  try{return await api.get(`/v1/model-operations-dashboard/export/${format}`,{...config({days}),responseType:'blob'})}
  catch(error){throw normalizeApiError(error)}
}
