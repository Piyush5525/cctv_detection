import { useState, useRef, useMemo, useCallback, useEffect } from 'react'
import MapboxMap, { Popup, Source, Layer } from 'react-map-gl/mapbox'
import 'mapbox-gl/dist/mapbox-gl.css'
import {
  ZoomIn, ZoomOut, Home, Camera, Box, Square, Radio,
} from 'lucide-react'
import { useIncidents } from '../context/IncidentContext'
import { useWebSocket } from '../context/WebSocketContext'
import { classNames, formatConfidence } from '../utils/format'
import {
  TYPE_LABELS, SEVERITY_ORDER, SEVERITY_LABEL, SEVERITY_HEX,
  severityChipClass, STATUS_LABEL, statusPillClass,
} from '../utils/incidentMeta'
import { IncidentHoverPreview } from '../components/IncidentHoverPreview'

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN

// India-wide fallback view, used only until real incident locations are
// available to fit bounds to (incidents are no longer Jaipur-only).
const INDIA_CENTER = { longitude: 79.0, latitude: 22.5 }
const INDIA_DEFAULT_ZOOM = 4

const INCIDENT_TYPES = ['violence', 'fall', 'women_safety', 'snatch', 'fire', 'crash', 'other']

const STYLE_2D = 'mapbox://styles/mapbox/dark-v11'
const STYLE_3D = 'mapbox://styles/mapbox/standard'

function IncidentPopupCard({ incident, longitude, latitude, onClose }) {
  return (
    <Popup
      longitude={longitude}
      latitude={latitude}
      onClose={onClose}
      closeButton={true}
      closeOnClick={false}
      offset={16}
      anchor="bottom"
      className="reticle-mapbox-popup"
    >
      <div className="w-56 font-sans">
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className={severityChipClass(incident.severity)}>{SEVERITY_LABEL[incident.severity]}</span>
          <span className={statusPillClass(incident.status)}>{STATUS_LABEL[incident.status]}</span>
        </div>
        <p className="text-sm font-semibold text-ink mb-0.5">{TYPE_LABELS[incident.incident_type]}</p>
        <p className="text-xs text-ink-faint mb-2">{incident.location?.camera_id} · {incident.location?.address}</p>
        <p className="text-[11px] font-mono text-ink-faint mb-2">
          {formatConfidence(incident.confidence)} · {new Date(incident.timestamp).toLocaleTimeString()}
        </p>
        <button
          onClick={() => window.location.assign('/incidents')}
          className="w-full text-xs font-medium bg-signal text-ground rounded-lg px-2 py-1.5"
        >
          Open
        </button>
      </div>
    </Popup>
  )
}

function MissingTokenNotice() {
  return (
    <div className="flex-1 flex items-center justify-center rounded-xl border border-ground-line bg-ground-panel">
      <div className="max-w-sm text-center p-6">
        <p className="text-sm font-semibold text-ink mb-2">Mapbox token missing</p>
        <p className="text-xs text-ink-faint">
          Set <code className="font-mono text-signal">VITE_MAPBOX_TOKEN</code> in{' '}
          <code className="font-mono">WomenSafety/frontend/.env</code>, then restart the dev server.
        </p>
      </div>
    </div>
  )
}

export function MapView() {
  const { allIncidents: incidents, heatmap, analytics } = useIncidents()
  const [selectedIncident, setSelectedIncident] = useState(null)
  const [hoveredIncident, setHoveredIncident] = useState(null)
  const [visibleTypes, setVisibleTypes] = useState(INCIDENT_TYPES)
  const [showPins, setShowPins] = useState(true)
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [showCoverage, setShowCoverage] = useState(false)
  const [is3D, setIs3D] = useState(false)
  const mapRef = useRef(null)
  const hoverTimeout = useRef(null)
  const { lastMessage } = useWebSocket()
  const [liveFlash, setLiveFlash] = useState(null)
  const hasFitBounds = useRef(false)

  // Most real scraped news headlines never name a specific street, so those
  // incidents only ever resolve to a city-centroid fallback coordinate. Tried
  // spreading same-coordinate incidents into a ring around that point so all
  // of them stayed visible, but at real map zoom levels that just reads as a
  // huge, meaningless circle -- worse than useful. The map now only plots
  // incidents that have a real, specific location; incidents stuck at a
  // city centroid are real data (visible in Live Incidents / the triage
  // queue) but aren't pinned on this map, since a city-level point isn't a
  // real map location to visualize.
  const filteredIncidents = useMemo(
    () => incidents
      .filter(i => visibleTypes.includes(i.incident_type))
      .filter(i => !(i.location?.address || '').toLowerCase().includes('unspecified')),
    [incidents, visibleTypes]
  )

  // Real, honest clustering instead of jitter/ring math: at this dataset's
  // density (most incidents only resolve to a city-level coordinate, not a
  // street address), spreading N points in a circle around one coordinate
  // always eventually looks like a ring once N is large enough -- there's
  // no jitter radius that fixes that, it's the wrong technique for this
  // density. Mapbox's native supercluster-based clustering (cluster: true
  // on the GeoJSON source below) aggregates nearby points into a single
  // sized/counted circle at low zoom and only shows individual points once
  // zoomed in close enough that they'd be visually distinct anyway.
  const incidentsGeoJSON = useMemo(() => ({
    type: 'FeatureCollection',
    features: filteredIncidents.map(inc => ({
      type: 'Feature',
      properties: {
        incident_id: inc.incident_id,
        severity: inc.severity,
      },
      geometry: { type: 'Point', coordinates: [inc.location.longitude, inc.location.latitude] },
    })),
  }), [filteredIncidents])

  const incidentById = useMemo(() => {
    const map = new Map()
    for (const inc of filteredIncidents) map.set(inc.incident_id, inc)
    return map
  }, [filteredIncidents])

  const typeCounts = useMemo(() => {
    const c = {}
    incidents.forEach(i => { c[i.incident_type] = (c[i.incident_type] || 0) + 1 })
    return c
  }, [incidents])

  // Camera FOV coverage as a GeoJSON circle layer rather than DOM Markers --
  // avoids react-map-gl Marker/React reconciliation glitches when many
  // fixed, non-interactive shapes render at once, and is cheaper to draw.
  const cameraLocations = useMemo(() => {
    const seen = new Map()
    incidents.forEach(i => {
      const cam = i.location?.camera_id
      if (cam && !seen.has(cam)) seen.set(cam, i.location)
    })
    return {
      type: 'FeatureCollection',
      features: [...seen.values()].map(loc => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [loc.longitude, loc.latitude] },
      })),
    }
  }, [incidents])

  const heatmapGeoJSON = useMemo(() => ({
    type: 'FeatureCollection',
    features: heatmap.map(point => ({
      type: 'Feature',
      properties: { weight: point.weight || 1 },
      geometry: { type: 'Point', coordinates: [point.longitude, point.latitude] },
    })),
  }), [heatmap])

  const hotspotCameras = useMemo(() => {
    const byCam = {}
    incidents.forEach(i => {
      const cam = i.location?.camera_id
      if (!cam) return
      byCam[cam] = byCam[cam] || {
        cam, address: i.location?.address, total: 0,
        sev: { critical: 0, high: 0, medium: 0, low: 0 },
        location: i.location,
      }
      byCam[cam].total++
      if (byCam[cam].sev[i.severity] !== undefined) byCam[cam].sev[i.severity]++
    })
    return Object.values(byCam).sort((a, b) => b.total - a.total).slice(0, 6)
  }, [incidents])

  const handleTypeToggle = (type) => {
    setVisibleTypes(prev => prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type])
  }

  const handleZoomIn = () => mapRef.current?.zoomIn()
  const handleZoomOut = () => mapRef.current?.zoomOut()

  // Frames every located incident in one view -- with nationwide data there's
  // no single fixed "home" city to fly back to, so Reset re-fits to whatever
  // is actually on the map instead of a hardcoded center/zoom.
  const fitToIncidents = useCallback((animate = true) => {
    if (!mapRef.current || filteredIncidents.length === 0) return
    let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity
    for (const inc of filteredIncidents) {
      const { longitude: lng, latitude: lat } = inc.location
      if (lng < minLng) minLng = lng
      if (lng > maxLng) maxLng = lng
      if (lat < minLat) minLat = lat
      if (lat > maxLat) maxLat = lat
    }
    mapRef.current.fitBounds(
      [[minLng, minLat], [maxLng, maxLat]],
      { padding: 80, maxZoom: 11, duration: animate ? 900 : 0, pitch: 0, bearing: 0 }
    )
  }, [filteredIncidents])

  const handleReset = () => fitToIncidents(true)

  // Auto-frame all located incidents once, the first time real data arrives
  // -- avoids opening on a fixed Jaipur view (or a near-empty India view)
  // when incidents span the whole country.
  useEffect(() => {
    if (hasFitBounds.current || filteredIncidents.length === 0) return
    fitToIncidents(false)
    hasFitBounds.current = true
  }, [filteredIncidents, fitToIncidents])

  const flyToCamera = useCallback((hotspot) => {
    if (!hotspot?.location || !mapRef.current) return
    mapRef.current.flyTo({
      center: [hotspot.location.longitude, hotspot.location.latitude],
      zoom: 15,
      duration: 900,
    })
    const match = incidents.find(i => i.location?.camera_id === hotspot.cam)
    if (match) setSelectedIncident(match)
  }, [incidents])

  const toggle3D = useCallback(() => {
    setIs3D(v => {
      const next = !v
      if (mapRef.current) {
        mapRef.current.easeTo({ pitch: next ? 55 : 0, bearing: next ? -17 : 0, duration: 600 })
      }
      return next
    })
  }, [])

  // Auto-follow a freshly-pushed critical incident, matching the Dashboard
  // feature-tile behavior -- the map surfaces new critical activity live
  // instead of requiring the operator to go hunt for it.
  useEffect(() => {
    const incident = lastMessage?.type === 'incident_created' ? lastMessage.data : null
    if (!incident?.location) return
    setLiveFlash(incident)
    const dismiss = setTimeout(() => setLiveFlash(null), 6000)
    if (incident.severity === 'critical' && mapRef.current) {
      mapRef.current.flyTo({
        center: [incident.location.longitude, incident.location.latitude],
        zoom: 14,
        duration: 1200,
      })
      setSelectedIncident(incident)
    }
    return () => clearTimeout(dismiss)
  }, [lastMessage])

  const handleHover = (incident) => {
    if (hoverTimeout.current) clearTimeout(hoverTimeout.current)
    setHoveredIncident(incident)
  }
  const handleLeave = () => {
    hoverTimeout.current = setTimeout(() => setHoveredIncident(null), 120)
  }

  // Native Mapbox layers (clusters + unclustered points) aren't React
  // elements, so their interactivity goes through the map's own click event
  // and queryRenderedFeatures rather than per-marker onClick props. Clicking
  // a cluster zooms in to expand it (the standard supercluster pattern);
  // clicking an individual point opens that incident.
  const handleMapClick = useCallback((e) => {
    const map = mapRef.current?.getMap?.()
    if (!map) return
    const features = map.queryRenderedFeatures(e.point, {
      layers: ['incident-clusters', 'incident-unclustered-point'],
    })
    if (features.length === 0) {
      setSelectedIncident(null)
      return
    }
    const feature = features[0]
    if (feature.layer.id === 'incident-clusters') {
      const clusterId = feature.properties.cluster_id
      const source = map.getSource('incidents')
      source.getClusterExpansionZoom(clusterId, (err, zoom) => {
        if (err) return
        map.easeTo({ center: feature.geometry.coordinates, zoom, duration: 500 })
      })
      return
    }
    const incident = incidentById.get(feature.properties.incident_id)
    if (incident) setSelectedIncident(incident)
  }, [incidentById])

  // Cursor feedback + hover preview for the native point layer, since it
  // has no per-feature onMouseEnter the way the old DOM Markers did.
  const handleMapMouseMove = useCallback((e) => {
    const map = mapRef.current?.getMap?.()
    if (!map) return
    const features = map.queryRenderedFeatures(e.point, { layers: ['incident-unclustered-point'] })
    if (features.length > 0) {
      map.getCanvas().style.cursor = 'pointer'
      const incident = incidentById.get(features[0].properties.incident_id)
      if (incident) handleHover(incident)
    } else {
      const clusterFeatures = map.queryRenderedFeatures(e.point, { layers: ['incident-clusters'] })
      map.getCanvas().style.cursor = clusterFeatures.length > 0 ? 'pointer' : ''
      handleLeave()
    }
  }, [incidentById])

  const cameraCount = new Set(incidents.map(i => i.location?.camera_id).filter(Boolean)).size
  const unlocatedCount = useMemo(
    () => incidents.filter(i => (i.location?.address || '').toLowerCase().includes('unspecified')).length,
    [incidents]
  )

  if (!MAPBOX_TOKEN) {
    return (
      <div className="h-[calc(100vh-6rem)] flex gap-4">
        <MissingTokenNotice />
      </div>
    )
  }

  return (
    <div className="h-[calc(100vh-6rem)] flex gap-4">
      {/* Sidebar */}
      <aside className="w-[260px] flex-shrink-0 flex flex-col gap-3 overflow-y-auto">
        <div className="card-sm">
          <p className="text-xs text-ink-muted">
            {cameraCount} data source{cameraCount === 1 ? '' : 's'} · {filteredIncidents.length} mapped incidents
          </p>
        </div>

        {unlocatedCount > 0 && (
          <div className="card-sm border-sev-medium/30 bg-sev-medium/[0.06]">
            <p className="text-xs text-ink-muted">
              <span className="text-sev-medium font-semibold">{unlocatedCount}</span> more incident{unlocatedCount === 1 ? '' : 's'} exist without a specific location (still visible in Live Incidents) and {unlocatedCount === 1 ? "isn't" : "aren't"} pinned here.
            </p>
          </div>
        )}

        <div className="card-sm">
          <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-2">Layers</p>
          <div className="space-y-2">
            <LayerToggle label="Incident pins (located only)" count={filteredIncidents.length} checked={showPins} onChange={setShowPins} />
            <LayerToggle label="Density heatmap" count={heatmap.length} checked={showHeatmap} onChange={setShowHeatmap} />
            <LayerToggle label="Data source coverage" count={cameraCount} checked={showCoverage} onChange={setShowCoverage} />
          </div>
        </div>

        <div className="card-sm">
          <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-2">Detection type</p>
          <div className="flex flex-wrap gap-1.5">
            {INCIDENT_TYPES.map(type => (
              <button
                key={type}
                onClick={() => handleTypeToggle(type)}
                className={classNames(
                  'px-2 py-1 rounded-lg text-[11px] font-medium transition-colors',
                  visibleTypes.includes(type)
                    ? 'bg-signal/15 text-signal border border-signal/30'
                    : 'text-ink-faint hover:text-ink hover:bg-white/5 border border-transparent'
                )}
              >
                {TYPE_LABELS[type]} <span className="font-mono">{typeCounts[type] || 0}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="card-sm flex-1 min-h-0 flex flex-col">
          <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-2">Hotspot locations</p>
          <div className="space-y-2 overflow-y-auto">
            {hotspotCameras.map(h => (
              <button
                key={h.cam}
                onClick={() => flyToCamera(h)}
                className="w-full text-left text-xs rounded-lg p-1.5 -mx-1.5 hover:bg-white/5 transition-colors cursor-pointer"
                title={`Fly to ${h.cam}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-ink font-medium">{h.cam}</span>
                  <span className="font-mono text-ink-faint">{h.total}</span>
                </div>
                <p className="text-[10px] text-ink-faint mb-1 truncate">{h.address}</p>
                <div className="h-1.5 rounded-full overflow-hidden flex bg-ground-line">
                  {SEVERITY_ORDER.map(sev => {
                    const pct = (h.sev[sev] / h.total) * 100
                    if (!pct) return null
                    return <div key={sev} style={{ width: `${pct}%`, background: SEVERITY_HEX[sev] }} />
                  })}
                </div>
              </button>
            ))}
            {hotspotCameras.length === 0 && <p className="text-xs text-ink-faint">No data yet</p>}
          </div>
        </div>

        <div className="card-sm">
          <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-2">Legend</p>
          <div className="space-y-1.5 text-xs">
            {SEVERITY_ORDER.map(sev => (
              <div key={sev} className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: SEVERITY_HEX[sev] }} />
                <span className="text-ink-muted">{SEVERITY_LABEL[sev]}</span>
              </div>
            ))}
            <div className="flex items-center gap-2 pt-1 border-t border-ground-line">
              <Camera className="w-3 h-3 text-ink-faint" />
              <span className="text-ink-muted">Data source</span>
            </div>
            <div className="flex items-center gap-2 pt-1 border-t border-ground-line">
              <span className="w-3.5 h-3.5 rounded-full flex items-center justify-center text-[7px] font-mono font-bold text-ink flex-shrink-0" style={{ background: 'rgba(91,155,255,0.28)', border: '1.5px solid rgba(91,155,255,0.7)' }}>N</span>
              <span className="text-ink-muted">Cluster — click to zoom in and split it apart</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Map */}
      <div className="flex-1 relative rounded-xl overflow-hidden border border-ground-line">
        {/* Live incident toast -- new WebSocket push while on this page */}
        {liveFlash && (
          <button
            onClick={() => { setSelectedIncident(liveFlash); setLiveFlash(null) }}
            className={classNames(
              'absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-3 py-1.5 rounded-full border backdrop-blur-sm shadow-lg animate-fade-up transition-colors',
              liveFlash.severity === 'critical'
                ? 'bg-sev-critical/15 border-sev-critical/40 text-sev-critical'
                : 'bg-signal/10 border-signal/30 text-signal'
            )}
          >
            <Radio className="w-3.5 h-3.5" />
            <span className="text-xs font-medium">
              New {TYPE_LABELS[liveFlash.incident_type] || liveFlash.incident_type} · {liveFlash.location?.camera_id}
            </span>
            <span className={severityChipClass(liveFlash.severity)}>{SEVERITY_LABEL[liveFlash.severity]}</span>
          </button>
        )}

        {/* 2D / 3D toggle */}
        <div className="absolute top-3 right-3 z-10 flex items-center gap-1 bg-ground-panel/95 backdrop-blur-sm border border-ground-line rounded-lg p-1">
          <button
            onClick={() => is3D && toggle3D()}
            className={classNames('flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors', !is3D ? 'bg-signal/15 text-signal' : 'text-ink-faint hover:text-ink')}
          >
            <Square className="w-3 h-3" /> 2D
          </button>
          <button
            onClick={() => !is3D && toggle3D()}
            className={classNames('flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors', is3D ? 'bg-signal/15 text-signal' : 'text-ink-faint hover:text-ink')}
          >
            <Box className="w-3 h-3" /> 3D
          </button>
        </div>

        <MapboxMap
          ref={mapRef}
          mapboxAccessToken={MAPBOX_TOKEN}
          initialViewState={{ longitude: INDIA_CENTER.longitude, latitude: INDIA_CENTER.latitude, zoom: INDIA_DEFAULT_ZOOM, pitch: 0, bearing: 0 }}
          mapStyle={is3D ? STYLE_3D : STYLE_2D}
          style={{ width: '100%', height: '100%' }}
          maxZoom={19}
          minZoom={3.5}
          onClick={handleMapClick}
          onMouseMove={handleMapMouseMove}
          interactiveLayerIds={['incident-clusters', 'incident-unclustered-point']}
        >
          {showCoverage && cameraLocations.features.length > 0 && (
            <Source id="camera-fov" type="geojson" data={cameraLocations}>
              <Layer
                id="camera-fov-fill"
                type="circle"
                paint={{
                  'circle-radius': 32,
                  'circle-color': '#7FE3D0',
                  'circle-opacity': 0.05,
                  'circle-stroke-width': 1,
                  'circle-stroke-color': '#7FE3D0',
                  'circle-stroke-opacity': 0.35,
                }}
              />
            </Source>
          )}

          {showHeatmap && heatmapGeoJSON.features.length > 0 && (
            <Source id="incident-heat" type="geojson" data={heatmapGeoJSON}>
              <Layer
                id="incident-heat-layer"
                type="heatmap"
                paint={{
                  'heatmap-weight': ['get', 'weight'],
                  'heatmap-intensity': 0.8,
                  'heatmap-radius': 34,
                  'heatmap-opacity': 0.55,
                  'heatmap-color': [
                    'interpolate', ['linear'], ['heatmap-density'],
                    0,    'rgba(0,0,0,0)',
                    0.2,  'rgba(91,155,255,0.5)',
                    0.4,  'rgba(245,197,66,0.6)',
                    0.6,  'rgba(255,138,31,0.7)',
                    1,    'rgba(255,75,62,0.85)',
                  ],
                }}
              />
            </Source>
          )}

          {showPins && (
            <Source
              id="incidents"
              type="geojson"
              data={incidentsGeoJSON}
              cluster={true}
              clusterMaxZoom={13}
              clusterRadius={50}
            >
              <Layer
                id="incident-clusters"
                type="circle"
                filter={['has', 'point_count']}
                paint={{
                  'circle-color': '#5B9BFF',
                  'circle-opacity': 0.28,
                  'circle-stroke-width': 2,
                  'circle-stroke-color': '#5B9BFF',
                  'circle-stroke-opacity': 0.7,
                  'circle-radius': [
                    'step', ['get', 'point_count'],
                    16, 10,
                    22, 25,
                    28, 50,
                    36, 100,
                    46,
                  ],
                }}
              />
              <Layer
                id="incident-cluster-count"
                type="symbol"
                filter={['has', 'point_count']}
                layout={{
                  'text-field': ['get', 'point_count_abbreviated'],
                  'text-font': ['DIN Pro Bold', 'Arial Unicode MS Bold'],
                  'text-size': 12,
                }}
                paint={{ 'text-color': '#ECE9E1' }}
              />
              <Layer
                id="incident-unclustered-point"
                type="circle"
                filter={['!', ['has', 'point_count']]}
                paint={{
                  'circle-radius': [
                    'match', ['get', 'severity'],
                    'critical', 11,
                    'high', 9,
                    'medium', 7.5,
                    'low', 6.5,
                    7,
                  ],
                  'circle-color': [
                    'match', ['get', 'severity'],
                    'critical', SEVERITY_HEX.critical,
                    'high', SEVERITY_HEX.high,
                    'medium', SEVERITY_HEX.medium,
                    'low', SEVERITY_HEX.low,
                    SEVERITY_HEX.low,
                  ],
                  'circle-stroke-width': 2,
                  'circle-stroke-color': 'rgba(11,13,12,0.6)',
                }}
              />
            </Source>
          )}

          {selectedIncident && (
            <IncidentPopupCard
              incident={selectedIncident}
              longitude={selectedIncident.location.longitude}
              latitude={selectedIncident.location.latitude}
              onClose={() => setSelectedIncident(null)}
            />
          )}

          {hoveredIncident && hoveredIncident.incident_id !== selectedIncident?.incident_id && (
            <Popup
              longitude={hoveredIncident.location.longitude}
              latitude={hoveredIncident.location.latitude}
              closeButton={false}
              closeOnClick={false}
              offset={16}
              anchor="bottom"
              className="reticle-mapbox-popup reticle-mapbox-popup-hover"
            >
              <div onMouseEnter={() => handleHover(hoveredIncident)} onMouseLeave={handleLeave}>
                <IncidentHoverPreview incident={hoveredIncident} />
              </div>
            </Popup>
          )}
        </MapboxMap>

        {/* Zoom / recenter controls */}
        <div className="absolute bottom-20 right-4 z-10 flex flex-col gap-1 bg-ground-panel/95 backdrop-blur-sm border border-ground-line rounded-lg p-1">
          <button onClick={handleZoomIn} className="p-2 rounded hover:bg-white/5 text-ink-muted" aria-label="Zoom in">
            <ZoomIn className="w-4 h-4" />
          </button>
          <button onClick={handleZoomOut} className="p-2 rounded hover:bg-white/5 text-ink-muted" aria-label="Zoom out">
            <ZoomOut className="w-4 h-4" />
          </button>
          <button onClick={handleReset} className="p-2 rounded hover:bg-white/5 text-ink-muted" aria-label="Recenter">
            <Home className="w-4 h-4" />
          </button>
        </div>

        <div className="absolute bottom-3 left-3 right-3 z-10 bg-ground-panel/95 backdrop-blur-sm border border-ground-line rounded-lg px-3 py-2 flex items-center justify-end">
          <span className="text-[10px] font-mono text-ink-faint">
            {analytics?.total_incidents ?? filteredIncidents.length} total
          </span>
        </div>
      </div>
    </div>
  )
}

function LayerToggle({ label, count, checked, onChange, disabled }) {
  return (
    <label className={classNames('flex items-center justify-between gap-2 text-xs cursor-pointer', disabled && 'opacity-50 cursor-not-allowed')}>
      <span className="flex items-center gap-2 text-ink-muted">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={e => onChange(e.target.checked)}
          className="w-3.5 h-3.5 rounded border-ground-line bg-ground accent-signal"
        />
        {label}
      </span>
      <span className="font-mono text-ink-faint">{count}</span>
    </label>
  )
}

export default MapView
