import client from './client'

export const predictOutcome = (court, disputeType, claimantType, remedy, facts = '') =>
  client.post('/api/predictor/predict', {
    court,
    dispute_type: disputeType,
    claimant_type: claimantType,
    remedy_sought: remedy,
    additional_facts: facts,
  }).then(r => r.data)
