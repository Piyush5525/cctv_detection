import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
})

// Fix pass item 8: state-changing / demo routes need the shared demo token.
const DEMO_TOKEN = import.meta.env.VITE_DEMO_TOKEN
api.interceptors.request.use(config => {
  if (DEMO_TOKEN && (config.method || 'get').toLowerCase() !== 'get') {
    config.headers['X-Demo-Token'] = DEMO_TOKEN
  }
  return config
})

api.interceptors.response.use(
  response => response,
  error => {
    if (error.code === 'ECONNABORTED') {
      console.error('Request timeout')
    }
    return Promise.reject(error)
  }
)

export const incidentsApi = {
  list: (params) => api.get('/incidents', { params }),
  get: (id) => api.get(`/incidents/${id}`),
  create: (data) => api.post('/incidents', data),
  update: (id, data) => api.patch(`/incidents/${id}`, data),
  delete: (id) => api.delete(`/incidents/${id}`),
  recent: (limit) => api.get('/incidents/recent', { params: { limit } }),
  analyticsSummary: () => api.get('/incidents/analytics/summary'),
  analyticsTrends: (hours) => api.get('/incidents/analytics/trends', { params: { hours } }),
  analyticsHeatmap: () => api.get('/incidents/analytics/heatmap'),
}

export const evidenceApi = {
  list: () => api.get('/evidence'),
  get: (filename) => api.get(`/evidence/${filename}`, { responseType: 'blob' }),
  thumbnail: (filename) => api.get(`/evidence/thumbnail/${filename}`, { responseType: 'blob' }),
  delete: (filename) => api.delete(`/evidence/${filename}`),
}

export const systemApi = {
  health: () => api.get('/system/health'),
  status: () => api.get('/system/status'),
}

export default api