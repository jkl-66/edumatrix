import {api,buildHeaders} from './common';const c=()=>({headers:buildHeaders()}),p=id=>`/v1/local-adapters/${encodeURIComponent(id)}`
export async function getLocalAdapterCatalog(){return(await api.get('/v1/local-adapters/catalog',c())).data}
export async function listLocalAdapterSessions(){return(await api.get('/v1/local-adapters',c())).data}
export async function createLocalAdapterSession(x){return(await api.post('/v1/local-adapters',x,c())).data}
export async function getLocalAdapterSession(id){return(await api.get(p(id),c())).data}
export async function runLocalAdapterAction(id,x){return(await api.post(`${p(id)}/actions`,x,c())).data}
