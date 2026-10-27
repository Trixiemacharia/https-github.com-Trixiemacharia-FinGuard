import { request } from './client.js';

export const authApi = {
  login: (body) => request('/auth/login/', 'POST', body, { auth: false, retryAuth: false }),
  register: (body) => request('/auth/register/', 'POST', body, { auth: false, retryAuth: false }),
  verifyMfa: (body) => request('/auth/mfa/verify/', 'POST', body, { auth: false, retryAuth: false }),
  logout: () => request('/auth/logout/', 'POST', {}),
};
export const walletApi = {
  get: () => request('/wallet/'),
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
  notifications: (after = 0) => request(`/fraud/notifications/?after=${after}`),
  alerts: (after = 0) => request(`/fraud/alerts/?after=${after}`),
  wsTicket: () => request('/fraud/ws-ticket/', 'POST', {}),
};
