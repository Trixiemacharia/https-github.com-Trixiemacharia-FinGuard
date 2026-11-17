import { api, request } from './client.js';

export const authApi = {
  login: (body) => request('/auth/login/', 'POST', body, { auth: false, retryAuth: false }),
  register: (body) => request('/auth/register/', 'POST', body, { auth: false, retryAuth: false }),
  verifyMfa: (body) => request('/auth/mfa/verify/', 'POST', body, { auth: false, retryAuth: false }),
  logout: () => request('/auth/logout/', 'POST', {}),
  me: () => request('/auth/me/'),
  sessions: () => request('/auth/sessions/'),
  revokeSession: (jti) => request(`/auth/sessions/${encodeURIComponent(jti)}/`, 'DELETE'),
  onboarding: () => request('/auth/onboarding/'),
  onboardingAction: (body) => request('/auth/onboarding/', 'POST', body),
  uploadOnboardingPhoto: (photo) => { const body = new FormData(); body.append('action', 'upload_selfie'); body.append('photo', photo); return api('/auth/onboarding/', { method: 'POST', body }); },
};
export const walletApi = {
  get: () => request('/wallet/'),
  security: () => request('/wallet/security/'),
  setFrozen: (frozen) => request('/wallet/security/', 'POST', { frozen }),
  transactions: (query = '') => request(`/wallet/transactions/${query}`),
  transaction: (id) => request(`/wallet/transactions/${id}/`),
  beneficiaries: () => request('/wallet/beneficiaries/'),
  addBeneficiary: (body) => request('/wallet/beneficiaries/', 'POST', body),
  removeBeneficiary: (id) => request(`/wallet/beneficiaries/${id}/`, 'DELETE'),
  renameBeneficiary: (id, nickname) => request(`/wallet/beneficiaries/${id}/`, 'PATCH', { nickname }),
  transfer: (body, key) => request('/wallet/transfer/', 'POST', body, { headers: { 'Idempotency-Key': key } }),
};
export const paymentApi = {
  list: () => request('/payments/mpesa/payments/'),
  detail: (id) => request(`/payments/mpesa/payments/${id}/`),
  stk: (body, key) => request('/payments/mpesa/stk/', 'POST', body, { headers: { 'Idempotency-Key': key } }),
};
export const fraudApi = {
  cases: (query = '') => request(`/fraud/cases/${query}`),
  case: (reference) => request(`/fraud/cases/${encodeURIComponent(reference)}/`),
  review: (reference, body) => request(`/fraud/cases/${encodeURIComponent(reference)}/review/`, 'POST', body),
  analytics: () => request('/fraud/analytics/'),
  alerts: (after = 0) => request(`/fraud/alerts/?after=${after}`),
  wsTicket: () => request('/fraud/ws-ticket/', 'POST', {}),
};
export const eventsApi = {
  notifications: (after = 0) => request(`/events/notifications/?after=${after}`),
  wsTicket: () => request('/events/ws-ticket/', 'POST', {}),
};
export const insightsApi = {
  overview: (months = 6) => request(`/insights/?months=${months}`),
  transactions: () => request('/insights/transactions/'),
  categorize: (id, category) => request(`/insights/transactions/${encodeURIComponent(id)}/category/`, 'PATCH', { category }),
  detectRecurring: () => request('/insights/recurring/detection/', 'POST', {}),
  detectionStatus: (id) => request(`/insights/recurring/detection/${encodeURIComponent(id)}/`),
  updateRecurring: (id, body) => request(`/insights/recurring/${id}/`, 'PATCH', body),
  report: (year, month) => request(`/insights/reports/${year}/${month}/`),
};
export const savingsApi = {
  goals: () => request('/savings/goals/'),
  createGoal: (body) => request('/savings/goals/', 'POST', body),
  updateGoal: (id, body) => request(`/savings/goals/${id}/`, 'PATCH', body),
  archiveGoal: (id) => request(`/savings/goals/${id}/`, 'DELETE'),
  contributions: (id) => request(`/savings/goals/${id}/contributions/`),
  move: (id, body, key) => request(`/savings/goals/${id}/contributions/`, 'POST', body, { headers: { 'Idempotency-Key': key } }),
  schedules: () => request('/savings/schedules/'),
  createSchedule: (body) => request('/savings/schedules/', 'POST', body),
  updateSchedule: (id, body) => request(`/savings/schedules/${id}/`, 'PATCH', body),
  recommendation: () => request('/savings/recommendations/'),
};
export const assistantApi = {
  capabilities: () => request('/assistant/capabilities/'),
  ask: (question) => request('/assistant/query/', 'POST', { question }),
};
