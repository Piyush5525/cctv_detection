import test from 'node:test'
import assert from 'node:assert/strict'
import { MIN_CHIP_ROUTE_KM, dispatchModel, dispatchPoints, haversineKm, incidentPoint } from '../src/utils/dispatchModel.mjs'

const HERE = { latitude: 26.9124, longitude: 75.7873 }
const svc = (title, lat, lng) => ({ title, gps_coordinates: { latitude: lat, longitude: lng } })
const route = (from, to, km, source = 'mapbox_driving') => ({ route_source: source, distance_km: km, eta_minutes: 4,
  geometry: { type: 'LineString', coordinates: [[from.longitude, from.latitude], [to.gps_coordinates.longitude, to.gps_coordinates.latitude]] } })

function incident(category, types) {
  const table = { hospital: svc('Hosp', 26.92, 75.79), police: svc('Pol', 26.905, 75.78), fire_station: svc('Fire', 26.93, 75.77) }
  const assignments = types.map((t, i) => ({ service_category: t, role: i === 0 ? 'primary' : 'secondary', status: 'available', service: table[t],
    alternatives: [svc('Alt ' + t, 26.9, 75.78)], route: route(HERE, table[t], 1.2) }))
  return { incident_id: 'i-' + category, category, latitude: HERE.latitude, longitude: HERE.longitude, dispatch_plan: { created_at: 't', assignments } }
}

test('every service marker is exactly at its plan position, in [lng, lat] order', () => {
  const inc = incident('fire', ['fire_station', 'hospital'])
  const { services } = dispatchModel(inc)
  for (const a of inc.dispatch_plan.assignments) {
    const m = services.find((s) => s.id === `${a.service_category}:p`)
    assert.equal(m.lng, a.service.gps_coordinates.longitude)
    assert.equal(m.lat, a.service.gps_coordinates.latitude)
    const alt = services.find((s) => s.id === `${a.service_category}:a0`)
    assert.equal(alt.lng, a.alternatives[0].gps_coordinates.longitude)
    assert.equal(alt.lat, a.alternatives[0].gps_coordinates.latitude)
  }
  assert.ok(services.every((s) => s.lng > 75 && s.lng < 76 && s.lat > 26 && s.lat < 27), 'lng ~75.x, lat ~26.x: not swapped')
})

test('a fire draws fire station and hospital only; a crash hospital and police only', () => {
  const fire = dispatchModel(incident('fire', ['fire_station', 'hospital']))
  assert.deepEqual(fire.types, ['fire_station', 'hospital'])
  assert.ok(!fire.services.some((s) => s.type === 'police') && !fire.routes.some((r) => r.type === 'police'))
  const crash = dispatchModel(incident('road_accident', ['hospital', 'police']))
  assert.deepEqual(crash.types, ['hospital', 'police'])
  assert.ok(!crash.services.some((s) => s.type === 'fire_station') && !crash.routes.some((r) => r.type === 'fire_station'))
})

test('one route per required type, starting at the incident location and ending at the service', () => {
  const inc = incident('road_accident', ['hospital', 'police'])
  const { routes } = dispatchModel(inc)
  assert.equal(routes.length, 2)
  for (const r of routes) {
    assert.deepEqual(r.geometry.coordinates[0], incidentPoint(inc))
    const plan = inc.dispatch_plan.assignments.find((a) => a.service_category === r.type).service.gps_coordinates
    assert.deepEqual(r.geometry.coordinates.at(-1), [plan.longitude, plan.latitude])
  }
})

test('routes and markers clear when the selection is cleared or the plan is missing (no stale routes)', () => {
  const a = dispatchModel(incident('fire', ['fire_station', 'hospital']))
  assert.ok(a.services.length && a.routes.length)
  for (const empty of [null, undefined, {}, { incident_id: 'x', dispatch_plan: null }, { incident_id: 'x', dispatch_plan: { assignments: [] } }]) {
    const m = dispatchModel(empty)
    assert.deepEqual([m.services.length, m.routes.length, m.types.length], [0, 0, 0])
  }
  const b = dispatchModel(incident('road_accident', ['hospital', 'police']))
  assert.ok(!b.routes.some((r) => r.type === 'fire_station'))
})

test('an unavailable service is not drawn and never replaced', () => {
  const inc = incident('fire', ['fire_station', 'hospital'])
  inc.dispatch_plan.assignments[0] = { service_category: 'fire_station', role: 'primary', status: 'unavailable', reason: 'No fire station found nearby' }
  const m = dispatchModel(inc)
  assert.deepEqual(m.types, ['hospital'])
  assert.ok(!m.services.some((s) => s.type === 'fire_station'))
})

test('straight-line routes are marked estimated; Mapbox routes are not', () => {
  const inc = incident('fire', ['fire_station', 'hospital'])
  inc.dispatch_plan.assignments[1].route.route_source = 'straight_line_fallback'
  const { routes } = dispatchModel(inc)
  assert.equal(routes.find((r) => r.type === 'fire_station').estimated, false)
  assert.equal(routes.find((r) => r.type === 'hospital').estimated, true)
})

test('fit-bounds points are the services plus the incident, all [lng, lat]', () => {
  const inc = incident('road_accident', ['hospital', 'police'])
  const pts = dispatchPoints(inc)
  assert.deepEqual(pts.at(-1), [HERE.longitude, HERE.latitude])
  assert.equal(pts.length, dispatchModel(inc).services.length + 1)
  assert.ok(pts.every(([lng, lat]) => lng > lat))
})

test('ETA chip is hidden on very short routes', () => {
  const inc = incident('fire', ['fire_station', 'hospital'])
  inc.dispatch_plan.assignments[1].route.distance_km = MIN_CHIP_ROUTE_KM - 0.05
  const { routes } = dispatchModel(inc)
  assert.equal(routes.find((r) => r.type === 'fire_station').showChip, true)
  assert.equal(routes.find((r) => r.type === 'hospital').showChip, false)
})

test('haversine helper is correct', () => {
  assert.ok(Math.abs(haversineKm([0, 0], [1, 0]) - 111.19) < 0.5)
  const a = incident('road_accident', ['hospital', 'police']).dispatch_plan.assignments[0]
  const km = haversineKm([HERE.longitude, HERE.latitude], [a.service.gps_coordinates.longitude, a.service.gps_coordinates.latitude])
  assert.ok(km > 0.5 && km < 1.5)
})
