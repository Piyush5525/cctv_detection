// Pure dispatch model: what the map draws for ONE incident, derived only from the incident and its dispatch plan.
// Coordinates are [lng, lat] everywhere here (Mapbox order); the API plan uses {latitude, longitude} objects and GeoJSON
// route geometry that is already [lng, lat].

export function midpoint(coords) {
  if (!coords?.length) return null
  if (coords.length === 2) return [(coords[0][0] + coords[1][0]) / 2, (coords[0][1] + coords[1][1]) / 2]
  const seg = []; let total = 0
  for (let i = 1; i < coords.length; i++) { const d = Math.hypot(coords[i][0] - coords[i - 1][0], coords[i][1] - coords[i - 1][1]); seg.push(d); total += d }
  let acc = 0
  for (let i = 0; i < seg.length; i++) {
    if (acc + seg[i] >= total / 2) { const t = (total / 2 - acc) / (seg[i] || 1); return [coords[i][0] + (coords[i + 1][0] - coords[i][0]) * t, coords[i][1] + (coords[i + 1][1] - coords[i][1]) * t] }
    acc += seg[i]
  }
  return coords[Math.floor(coords.length / 2)]
}

/** Great-circle distance in km between two [lng, lat] points. */
export function haversineKm(a, b) {
  const rad = (d) => (d * Math.PI) / 180
  const dLat = rad(b[1] - a[1]), dLng = rad(b[0] - a[0])
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLng / 2) ** 2
  return 6371 * 2 * Math.asin(Math.sqrt(h))
}

export const MIN_CHIP_ROUTE_KM = 0.3   // shorter routes get no ETA chip (it would sit on the markers); the card still shows it

// Services to draw for an incident: [{ id, type, rank, lng, lat, title }] + routes [{ id, type, geometry, estimated, km, eta, mid, showChip }]
export function dispatchModel(incident) {
  const plan = incident?.dispatch_plan
  const services = [], routes = []
  if (!plan?.assignments) return { services, routes, types: [] }
  const types = []
  plan.assignments.forEach((a) => {
    if (a.status !== 'available' || !a.service?.gps_coordinates) return
    const type = a.service_category
    types.push(type)
    const g = a.service.gps_coordinates
    services.push({ id: `${type}:p`, type, rank: 'primary', lng: g.longitude, lat: g.latitude, title: a.service.title })
    ;(a.alternatives || []).forEach((alt, i) => {
      const ag = alt.gps_coordinates
      if (ag) services.push({ id: `${type}:a${i}`, type, rank: 'alt', lng: ag.longitude, lat: ag.latitude, title: alt.title })
    })
    const geom = a.route?.geometry
    if (geom?.coordinates?.length >= 2) {
      const estimated = a.route.route_source !== 'mapbox_driving'
      routes.push({ id: `${type}:r`, type, geometry: geom, estimated, km: a.route.distance_km, eta: a.route.eta_minutes, mid: midpoint(geom.coordinates),
                    showChip: (a.route.distance_km ?? 0) >= MIN_CHIP_ROUTE_KM })
    }
  })
  return { services, routes, types }
}

/** The incident's own snapshot location as [lng, lat], or null. */
export function incidentPoint(incident) {
  return incident?.longitude != null && incident?.latitude != null ? [incident.longitude, incident.latitude] : null
}

export function dispatchPoints(incident) {
  const { services } = dispatchModel(incident)
  const pts = services.map((s) => [s.lng, s.lat])
  const here = incidentPoint(incident)
  if (pts.length && here) pts.push(here)
  return pts
}
