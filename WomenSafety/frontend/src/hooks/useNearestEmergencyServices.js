import { useEffect, useRef, useState } from 'react'
import axios from 'axios'

// Simple per-session cache keyed by rounded coordinates -- an incident's
// location doesn't move, and the Overpass-backed endpoint is already slow
// (real network calls to a public, shared instance), so avoid refetching it
// every time the same incident is reselected.
const cache = new Map()

function keyFor(lat, lng) {
  return `${lat.toFixed(3)},${lng.toFixed(3)}`
}

export function useNearestEmergencyServices(latitude, longitude) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const requestId = useRef(0)

  useEffect(() => {
    if (latitude == null || longitude == null) {
      setData(null)
      return
    }
    const key = keyFor(latitude, longitude)
    if (cache.has(key)) {
      setData(cache.get(key))
      setError(null)
      return
    }
    const myRequest = ++requestId.current
    setLoading(true)
    setError(null)
    axios
      .get('/api/v1/emergency/nearest', { params: { latitude, longitude }, timeout: 30000 })
      .then(res => {
        if (requestId.current !== myRequest) return
        cache.set(key, res.data)
        setData(res.data)
      })
      .catch(err => {
        if (requestId.current !== myRequest) return
        setError(err)
      })
      .finally(() => {
        if (requestId.current !== myRequest) return
        setLoading(false)
      })
  }, [latitude, longitude])

  return { data, loading, error }
}

export default useNearestEmergencyServices
