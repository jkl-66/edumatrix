import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })
const data = async promise => (await promise).data

export const getCourseSharingWorkspace = () => data(api.get('/v1/course-sharing/workspace', config()))
export const publishCourseShare = payload => data(api.post('/v1/course-sharing/releases', payload, config()))
export const createCourseCopy = releaseId => data(api.post(`/v1/course-sharing/releases/${encodeURIComponent(releaseId)}/copies`, {}, config()))
export const decideCourseUpdate = (copyId, payload) => data(api.post(`/v1/course-sharing/copies/${encodeURIComponent(copyId)}/decisions`, payload, config()))
export const propagateCourseWithdrawals = () => data(api.post('/v1/course-sharing/withdrawals/propagate', {}, config()))
