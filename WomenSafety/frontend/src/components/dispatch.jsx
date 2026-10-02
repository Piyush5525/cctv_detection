// Dispatch map layer + dispatch card. The plan arrives already filtered by the backend
// (api/core/config.py DISPATCH_RULES), so nothing here decides which services an incident needs.
import { useEffect, useMemo, useRef } from 'react'
import { Marker, useMap } from 'react-map-gl/mapbox'
import toast from 'react-hot-toast'
import { dispatchModel, dispatchPoints, incidentPoint } from '../utils/dispatchModel.mjs'

const REDUCED =
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

// ─── Icons: rounded badge + white glyph, one style. Shape AND colour differ. ───
export const SERVICE_STYLE = {
  hospital: { color: '#E5484D', label: 'Hospital', shape: 'circle' },
  police: { color: '#3B82F6', label: 'Police station', shape: 'shield' },
  fire_station: { color: '#F97316', label: 'Fire station', shape: 'square' },
}
const styleOf = (type) => SERVICE_STYLE[type] || { color: '#7FE3D0', label: String(type).replace(/_/g, ' '), shape: 'circle' }

function badgeShape(type, color) {
  if (type === 'police') return <path d="M24 3.5 40 9.5v13.8c0 9.2-6.4 15.9-16 20.2C14.4 39.2 8 32.5 8 23.3V9.5z" fill={color} />
  if (type === 'fire_station') return <rect x="4" y="4" width="40" height="40" rx="12" fill={color} />
  return <circle cx="24" cy="24" r="20" fill={color} />
}
function glyph(type) {
  if (type === 'police') {
    return <path d="m24 12 3.1 6.4 7 1-5.1 4.9 1.2 7L24 28l-6.2 3.3 1.2-7-5.1-4.9 7-1z" fill="#fff" />
  }
  if (type === 'fire_station') {
    return <path d="M24 10c1.8 5.6 9 8.6 9 17 0 5.7-4 10-9 10s-9-4.300-9-10c0-4 2-7 4-9 0 4 2.200 5.200 3.500 5.200C21.500 18.500 22 14 24 10z" fill="#fff" />
  }
  return <path d="M21 13h6v8h8v6h-8v8h-6v-8h-8v-6h8z" fill="#fff" />
}

export function ServiceIcon({ type, size = 28, title }) {
  const { color, label } = styleOf(type)
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" role="img" aria-label={title || label}
         style={{ filter: 'drop-shadow(0 2px 3px rgba(0,0,0,0.45))', flexShrink: 0 }}>
      {badgeShape(type, color)}
      {glyph(type)}
    </svg>
  )
}

function svgMarkup(type) {
  const { color } = styleOf(type)
  const shape = type === 'police'
    ? `<path d="M24 3.5 40 9.5v13.8c0 9.2-6.4 15.9-16 20.2C14.4 39.2 8 32.5 8 23.3V9.5z" fill="${color}"/>`
    : type === 'fire_station' ? `<rect x="4" y="4" width="40" height="40" rx="12" fill="${color}"/>` : `<circle cx="24" cy="24" r="20" fill="${color}"/>`
  const g = type === 'police'
    ? '<path d="m24 12 3.1 6.4 7 1-5.1 4.9 1.2 7L24 28l-6.2 3.3 1.2-7-5.1-4.9 7-1z" fill="#fff"/>'
    : type === 'fire_station' ? '<path d="M24 10c1.8 5.6 9 8.6 9 17 0 5.7-4 10-9 10s-9-4.3-9-10c0-4 2-7 4-9 0 4 2.2 5.2 3.5 5.2C21.5 18.5 22 14 24 10z" fill="#fff"/>'
      : '<path d="M21 13h6v8h8v6h-8v8h-6v-8h-8v-6h8z" fill="#fff"/>'
  return `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">${shape}${g}</svg>`
}

// Draw the same SVG (plus a soft shadow) into a canvas and register it as a map image.
function loadImage(type) {
  return new Promise((resolve, reject) => {
    const img = new Image(48, 48)
    img.onload = () => {
      const size = 64, ratio = 2
      const canvas = document.createElement('canvas')
      canvas.width = canvas.height = size * ratio
      const ctx = canvas.getContext('2d')
      ctx.scale(ratio, ratio)
      ctx.shadowColor = 'rgba(0,0,0,0.5)'
      ctx.shadowBlur = 5
      ctx.shadowOffsetY = 2
      ctx.drawImage(img, 8, 6, 48, 48)
      resolve(ctx.getImageData(0, 0, size * ratio, size * ratio))
    }
    img.onerror = reject
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgMarkup(type))}`
  })
}

// ─── Map layer plumbing (created once; data updated in place) ──────────────
const SRC_SVC = 'dispatch-services', SRC_RT = 'dispatch-routes'
const EMPTY = { type: 'FeatureCollection', features: [] }
const stats = (typeof window !== 'undefined' && (window.__dispatchStats = window.__dispatchStats || { sourceAdds: 0, layerAdds: 0, imageAdds: 0, dataUpdates: 0 })) || {}

// Returns true only if something had to be created (so callers re-render data only then).
async function ensureLayers(map) {
  let created = false
  for (const type of Object.keys(SERVICE_STYLE)) {
    if (!map.hasImage(`svc-${type}`)) {
      const data = await loadImage(type)
      if (!map.hasImage(`svc-${type}`)) { map.addImage(`svc-${type}`, data, { pixelRatio: 2 }); stats.imageAdds++; created = true }
    }
  }
  if (!map.getSource(SRC_RT)) { map.addSource(SRC_RT, { type: 'geojson', data: EMPTY, lineMetrics: true }); stats.sourceAdds++; created = true }
  if (!map.getSource(SRC_SVC)) { map.addSource(SRC_SVC, { type: 'geojson', data: EMPTY }); stats.sourceAdds++; created = true }
  const add = (layer) => { if (!map.getLayer(layer.id)) { map.addLayer(layer); stats.layerAdds++; created = true } }
  add({
    id: 'dispatch-routes-est', type: 'line', source: SRC_RT, filter: ['==', ['get', 'estimated'], true],
    layout: { 'line-cap': 'round' },
    paint: { 'line-color': ['get', 'color'], 'line-width': ['case', ['get', 'hl'], 4.5, 3], 'line-dasharray': [1.6, 1.6], 'line-opacity': ['*', 0.85, ['get', 'appear']] },
  })
  add({
    id: 'dispatch-routes-road', type: 'line', source: SRC_RT, filter: ['!=', ['get', 'estimated'], true],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ['get', 'color'], 'line-width': ['case', ['get', 'hl'], 6, 4], 'line-opacity': 0.92 },
  })
  add({
    id: 'dispatch-ring', type: 'circle', source: SRC_SVC, filter: ['==', ['get', 'rank'], 'primary'],
    paint: { 'circle-radius': 26, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2.5, 'circle-stroke-opacity': ['case', ['get', 'hl'], 0.95, 0] },
  })
  add({
    id: 'dispatch-icons', type: 'symbol', source: SRC_SVC,
    layout: {
      'icon-image': ['concat', 'svc-', ['get', 'type']], 'icon-allow-overlap': true, 'icon-ignore-placement': true,
      'icon-size': ['*', ['case', ['==', ['get', 'rank'], 'primary'], 1, 0.62], ['+', 0.6, ['*', 0.4, ['get', 'appear']]], ['case', ['get', 'hl'], 1.2, 1]],
    },
    paint: { 'icon-opacity': ['get', 'appear'] },
  })
  return created
}

const setData = (map, id, data) => { map.getSource(id)?.setData(data); stats.dataUpdates++ }
const easeOut = (t) => 1 - Math.pow(1 - t, 3)
const clamp01 = (v) => Math.max(0, Math.min(1, v))

export { dispatchModel, dispatchPoints }

export function fitToDispatch(mapRef, incident) {
  const pts = dispatchPoints(incident)
  if (!mapRef?.current || pts.length < 2) return false
  const lngs = pts.map((p) => p[0]), lats = pts.map((p) => p[1])
  // The detail panel sits beside the map (outside the canvas), so symmetric padding is enough.
  mapRef.current.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]], {
    padding: { top: 90, bottom: 90, left: 90, right: 90 }, maxZoom: 15, duration: REDUCED ? 0 : 900, easing: easeOut,
  })
  return true
}

// Rendered inside <Map>. Owns the GL sources/layers; draws only the selected incident's services.
export function DispatchLayer({ incident, hot, onHot }) {
  const { current: mapRef } = useMap()
  const hotRef = useRef(hot)
  const modelRef = useRef({ services: [], routes: [] })
  const animRef = useRef(0)
  const progressRef = useRef(1)
  const appearRef = useRef({})
  const model = useMemo(() => dispatchModel(incident), [incident?.incident_id, incident?.dispatch_plan?.created_at])  // eslint-disable-line react-hooks/exhaustive-deps
  const here = incidentPoint(incident)
  modelRef.current = model
  hotRef.current = hot

  const render = (map) => {
    const m = modelRef.current
    const h = hotRef.current
    setData(map, SRC_SVC, {
      type: 'FeatureCollection',
      features: m.services.map((s) => ({
        type: 'Feature', geometry: { type: 'Point', coordinates: [s.lng, s.lat] },
        properties: { id: s.id, type: s.type, rank: s.rank, title: s.title, hl: h === s.type, appear: appearRef.current[s.id] ?? 1 },
      })),
    })
    setData(map, SRC_RT, {
      type: 'FeatureCollection',
      features: m.routes.map((r) => ({
        type: 'Feature', geometry: r.geometry,
        properties: { id: r.id, type: r.type, color: styleOf(r.type).color, estimated: r.estimated, hl: h === r.type, appear: appearRef.current[r.id] ?? 1 },
      })),
    })
    try { map.setPaintProperty('dispatch-routes-road', 'line-trim-offset', [0, 1 - progressRef.current]) } catch { /* older GL: no trim, line just appears */ }
  }

  // create layers once per style; re-run (idempotently) when the style reloads
  useEffect(() => {
    const map = mapRef?.getMap?.()
    if (!map) return undefined
    let alive = true
    let busy = false
    if (typeof window !== 'undefined') window.__dispatchMap = map   // diagnostics / integration checks only
    const ensure = async () => {
      if (busy) return  // (isStyleLoaded() is false while tiles load, so don't gate on it; addSource throws until the style is ready and we retry)
      busy = true
      try { if (await ensureLayers(map) && alive) render(map) } catch { /* retried on next styledata */ } finally { busy = false }
    }
    ensure()
    map.on('styledata', ensure); map.on('style.load', ensure); map.on('load', ensure); map.on('idle', ensure)
    const enter = (e) => { const t = e.features?.[0]?.properties?.type; if (t) { map.getCanvas().style.cursor = 'pointer'; onHot?.(t) } }
    const leave = () => { map.getCanvas().style.cursor = ''; onHot?.(null) }
    map.on('mousemove', 'dispatch-icons', enter); map.on('mouseleave', 'dispatch-icons', leave)
    return () => {
      alive = false
      map.off('styledata', ensure); map.off('style.load', ensure); map.off('load', ensure); map.off('idle', ensure)
      map.off('mousemove', 'dispatch-icons', enter); map.off('mouseleave', 'dispatch-icons', leave)
      cancelAnimationFrame(animRef.current)
      try { ['dispatch-icons', 'dispatch-ring', 'dispatch-routes-road', 'dispatch-routes-est'].forEach((l) => map.getLayer(l) && map.removeLayer(l)); [SRC_SVC, SRC_RT].forEach((s) => map.getSource(s) && map.removeSource(s)) } catch { /* map already gone */ }
    }
  }, [mapRef])  // eslint-disable-line react-hooks/exhaustive-deps

  // selection / plan change: staggered fade+scale in (60 ms apart) and route draw-in
  useEffect(() => {
    const map = mapRef?.getMap?.()
    if (!map || !map.getSource(SRC_SVC)) { appearRef.current = {}; return undefined }
    cancelAnimationFrame(animRef.current)
    const ids = [...model.services.map((s) => s.id), ...model.routes.map((r) => r.id)]
    if (REDUCED || !ids.length) {
      appearRef.current = {}; progressRef.current = 1; render(map); return undefined
    }
    appearRef.current = Object.fromEntries(ids.map((id) => [id, 0])); progressRef.current = 0
    const start = performance.now()
    const frame = (now) => {
      const t = now - start
      stats.frames = (stats.frames || 0) + 1
      model.services.forEach((s, i) => { appearRef.current[s.id] = easeOut(clamp01((t - i * 60) / 320)) })
      model.routes.forEach((r, i) => { appearRef.current[r.id] = easeOut(clamp01((t - 120 - i * 60) / 300)) })
      progressRef.current = easeOut(clamp01((t - 150) / 800))
      render(map)
      if (t < 1300 + ids.length * 60) animRef.current = requestAnimationFrame(frame)
    }
    animRef.current = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(animRef.current)
  }, [model, mapRef])  // eslint-disable-line react-hooks/exhaustive-deps

  // hover highlight: data-only update (no layer work)
  useEffect(() => {
    const map = mapRef?.getMap?.()
    if (map?.getSource(SRC_SVC)) render(map)
  }, [hot])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      {here && (
        <Marker longitude={here[0]} latitude={here[1]} anchor="bottom">
          <div className="incident-pin" role="img" aria-label="Incident location" title="Incident location">
            <svg width="30" height="38" viewBox="0 0 30 38"><path d="M15 37C15 37 2 23.5 2 14.5a13 13 0 0 1 26 0C28 23.5 15 37 15 37z" fill="#FF4B3E" stroke="#fff" strokeWidth="2.5" /><circle cx="15" cy="14.5" r="5" fill="#fff" /></svg>
          </div>
        </Marker>
      )}
      {model.routes.map((r) => r.mid && r.showChip && (
        <Marker key={r.id} longitude={r.mid[0]} latitude={r.mid[1]} anchor="center" offset={[0, -16]}>
          <div className={`eta-chip ${hot === r.type ? 'hot' : ''}`} style={{ '--chip-color': styleOf(r.type).color }}
               aria-label={`${styleOf(r.type).label}: ${r.eta ?? '?'} minutes, ${r.km ?? '?'} kilometres${r.estimated ? ', estimated' : ''}`}>
            {r.estimated ? 'est. ' : ''}{r.eta ?? '?'} min · {r.km ?? '?'} km
          </div>
        </Marker>
      ))}
    </>
  )
}

export function DispatchLegend({ types }) {
  if (!types?.length) return null
  return (
    <div className="map-legend dispatch-legend" role="img" aria-label="Dispatch legend">
      {[...new Set(types)].map((t) => (
        <div className="legend-item" key={t}>
          <ServiceIcon type={t} size={18} />
          <span>{styleOf(t).label}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Right-hand dispatch card ──────────────────────────────────────────────
function copyPhone(phone) {
  navigator.clipboard?.writeText(phone).then(() => toast.success('Phone number copied'), () => toast.error('Could not copy'))
}

export function DispatchCard({ incident, hot, onHot }) {
  const plan = incident?.dispatch_plan
  const rows = useMemo(() => {
    if (plan?.assignments?.length) return plan.assignments
    return (plan?.required_services || []).map((t, i) => ({ service_category: t, role: i === 0 ? 'primary' : 'secondary', status: 'unavailable', reason: `${styleOf(t).label} lookup unavailable` }))
  }, [plan])
  if (!rows.length) return <p className="detail-muted">Dispatch lookup pending or unavailable.</p>
  return (
    <div className="dispatch-list" key={incident.incident_id}>
      {rows.map((a) => {
        const type = a.service_category
        const svc = a.service
        const route = a.route
        const isHot = hot === type
        if (a.status !== 'available' || !svc) {
          return (
            <div key={type} className="dispatch-row muted" tabIndex={0} onMouseEnter={() => onHot?.(type)} onMouseLeave={() => onHot?.(null)}>
              <ServiceIcon type={type} size={24} />
              <span className="dispatch-unavailable">{a.reason || `No ${styleOf(type).label.toLowerCase()} found nearby`}</span>
            </div>
          )
        }
        return (
          <div key={type} className={`dispatch-row ${isHot ? 'hot' : ''}`} tabIndex={0}
               style={{ '--row-color': styleOf(type).color }}
               onMouseEnter={() => onHot?.(type)} onMouseLeave={() => onHot?.(null)} onFocus={() => onHot?.(type)} onBlur={() => onHot?.(null)}>
            <ServiceIcon type={type} size={30} />
            <div className="dispatch-row-body">
              <div className="dispatch-row-top">
                <span className="dispatch-name">{svc.title || 'Unknown'}</span>
                {a.role === 'primary' && <span className="nearest-badge">Nearest</span>}
              </div>
              <div className="dispatch-row-meta">
                <span>{route?.distance_km ?? svc.distance_km ?? '?'} km</span>
                <span className="dispatch-dot">·</span>
                <span>{route?.eta_minutes != null ? `${route.eta_minutes} min ETA` : 'ETA n/a'}</span>
                {route && route.route_source !== 'mapbox_driving' && <span className="dispatch-fallback-note">estimated</span>}
              </div>
              {svc.phone ? (
                <button type="button" className="dispatch-phone-btn" onClick={() => copyPhone(svc.phone)} title="Tap to copy" aria-label={`Copy phone number of ${svc.title}`}>
                  {svc.phone}
                </button>
              ) : <span className="dispatch-phone">No phone listed</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}
