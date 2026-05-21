import client from './client'

export const checkCompliance = (actionType, description, companyType = '') =>
  client.post('/api/compliance/check', {
    action_type: actionType,
    description,
    company_type: companyType,
  }).then(r => r.data)
