import { useRef } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip as LeafletTooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { MapPin } from 'lucide-react'

const CENTER = [26.9124, 75.7873]
const TYPE_COLORS = {
  violence: '#f87171', fall: '#fbbf24', women_safety: '#60a5fa',
  snatch: '#a78bfa', fire: '#fb923c', crash: '#f97316', other: '#94a3b8',
}

export function MiniMap({ heatmap = [], incidents = [] }) {
  const points = [
    ...heatmap,
    ...incidents.map(i => ({
      latitude: i.location?.latitude,
      longitude: i.location?.longitude,
      weight: i.severity === 'critical' ? 3 : i.severity === 'high' ? 2 : 1,
      incident_type: i.incident_type,
      severity: i.severity,
    })).filter(p => p.latitude && p.longitude),
  ]

  if (points.length === 0) {
    return (
      <div className="card flex items-center justify-center" style={{ minHeight: 200 }}>
        <div className="text-center">
          <MapPin className="w-8 h-8 mx-auto mb-2 text-slate-700" />
          <p className="text-xs text-slate-600">No location data</p>
        </div>
      </div>
    )
  }

  return (
    <div className="card p-0 overflow-hidden" style={{ minHeight: 200 }}>
      <div className="px-4 py-3 border-b border-[#1a2540]">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Incident Map</span>
      </div>
      <MapContainer
        center={CENTER}
        zoom={11}
        scrollWheelZoom={false}
        style={{ height: 200, width: '100%', background: '#080d18' }}
        zoomControl={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />
        {points.map((p, i) => (
          <CircleMarker
            key={i}
            center={[p.latitude, p.longitude]}
            radius={Math.max(5, (p.weight || 1) * 4)}
            pathOptions={{
              color: TYPE_COLORS[p.incident_type] || '#94a3b8',
              fillColor: TYPE_COLORS[p.incident_type] || '#94a3b8',
              fillOpacity: 0.7,
              weight: 1.5,
            }}
          >
            <LeafletTooltip direction="top" offset={[0, -8]} opacity={0.95}>
              <span className="capitalize text-xs">{p.incident_type?.replace('_', ' ')} · {p.severity}</span>
            </LeafletTooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}

export default MiniMap
