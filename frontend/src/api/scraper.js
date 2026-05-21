import client from './client'

export const runScraper    = (params) => client.post('/api/scraper/run', params).then(r => r.data)
export const scraperStatus = ()       => client.get('/api/scraper/status').then(r => r.data)
export const scraperHistory= ()       => client.get('/api/scraper/history').then(r => r.data)
export const scraperCourts = ()       => client.get('/api/scraper/courts').then(r => r.data)
export const graphStats    = ()       => client.get('/graph/stats').then(r => r.data)
export const healthCheck   = ()       => client.get('/health').then(r => r.data)
