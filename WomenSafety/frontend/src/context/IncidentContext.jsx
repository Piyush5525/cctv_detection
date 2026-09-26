import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import axios from 'axios'

const API_BASE = '/api/v1'

const IncidentContext = createContext(null)

export function IncidentProvider({ children }) {
  const [incidents, setIncidents] = useState([])
  const [selectedIncident, setSelectedIncident] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [pagination, setPagination] = useState({ page: 1, pageSize: 20, total: 0, totalPages: 0 })
  const [filters, setFilters] = useState({})
  const [sortConfig, setSortConfig] = useState({ key: 'timestamp', desc: true })
  const [analytics, setAnalytics] = useState(null)
  const [trends, setTrends] = useState([])
  const [heatmap, setHeatmap] = useState([])
  const [systemHealth, setSystemHealth] = useState(null)

  const fetchIncidents = useCallback(async (page = 1, newFilters = {}, append = false) => {
    setIsLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.append('page', page)
      params.append('page_size', pagination.pageSize)
      params.append('sort_by', sortConfig.key)
      params.append('sort_desc', sortConfig.desc)

      Object.entries({ ...filters, ...newFilters }).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          if (Array.isArray(value)) {
            value.forEach(v => params.append(key, v))
          } else {
            params.append(key, value)
          }
        }
      })

      const response = await axios.get(`${API_BASE}/incidents?${params.toString()}`)
      const data = response.data

      if (append) {
        setIncidents(prev => [...prev, ...data.incidents])
      } else {
        setIncidents(data.incidents)
      }
      setPagination(prev => ({ ...prev, ...data, page: data.page }))
    } catch (err) {
      setError(err.message)
      console.error('Failed to fetch incidents:', err)
    } finally {
      setIsLoading(false)
    }
  }, [filters, pagination.pageSize, sortConfig])

  const fetchAnalytics = useCallback(async () => {
    try {
      const [summaryRes, trendsRes, heatmapRes] = await Promise.all([
        axios.get(`${API_BASE}/incidents/analytics/summary`),
        axios.get(`${API_BASE}/incidents/analytics/trends?hours=24`),
        axios.get(`${API_BASE}/incidents/analytics/heatmap`),
      ])
      setAnalytics(summaryRes.data)
      setTrends(trendsRes.data)
      setHeatmap(heatmapRes.data)
    } catch (err) {
      console.error('Failed to fetch analytics:', err)
    }
  }, [])

  const fetchSystemHealth = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/system/health`)
      setSystemHealth(res.data)
    } catch (err) {
      console.error('Failed to fetch system health:', err)
    }
  }, [])

  const createIncident = useCallback(async (incidentData) => {
    const response = await axios.post(`${API_BASE}/incidents`, incidentData)
    setIncidents(prev => [response.data, ...prev])
    return response.data
  }, [])

  const updateIncident = useCallback(async (incidentId, updateData) => {
    const response = await axios.patch(`${API_BASE}/incidents/${incidentId}`, updateData)
    setIncidents(prev => prev.map(i => i.incident_id === incidentId ? response.data : i))
    if (selectedIncident?.incident_id === incidentId) {
      setSelectedIncident(response.data)
    }
    return response.data
  }, [selectedIncident])

  const deleteIncident = useCallback(async (incidentId) => {
    await axios.delete(`${API_BASE}/incidents/${incidentId}`)
    setIncidents(prev => prev.filter(i => i.incident_id !== incidentId))
  }, [])

  const refetch = useCallback(() => {
    fetchIncidents(1)
    fetchAnalytics()
  }, [fetchIncidents, fetchAnalytics])

  useEffect(() => {
    fetchIncidents(1)
    fetchAnalytics()
    fetchSystemHealth()
  }, [])

  const value = useMemo(() => ({
    incidents,
    selectedIncident,
    setSelectedIncident,
    isLoading,
    error,
    pagination,
    filters,
    setFilters,
    sortConfig,
    setSortConfig,
    analytics,
    trends,
    heatmap,
    systemHealth,
    fetchIncidents,
    fetchAnalytics,
    fetchSystemHealth,
    createIncident,
    updateIncident,
    deleteIncident,
    refetch,
  }), [
    incidents, selectedIncident, isLoading, error, pagination, filters, sortConfig,
    analytics, trends, heatmap, systemHealth,
    fetchIncidents, fetchAnalytics, fetchSystemHealth,
    createIncident, updateIncident, deleteIncident, refetch
  ])

  return (
    <IncidentContext.Provider value={value}>
      {children}
    </IncidentContext.Provider>
  )
}

export function useIncidents() {
  const context = useContext(IncidentContext)
  if (!context) {
    throw new Error('useIncidents must be used within an IncidentProvider')
  }
  return context
}