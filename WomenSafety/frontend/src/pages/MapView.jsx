import { useState, useRef, useEffect } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, LayerGroup } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { 
  MapPin, 
  Layers, 
  Target, 
  Search, 
  ZoomIn, 
  ZoomOut,
  Home,
  Filter,
  AlertTriangle,
  Flame,
  Car,
  Shield,
  Activity,
  Video,
} from 'lucide-react'
import { useIncidents } from '../context/IncidentContext'
import { classNames } from '../utils/format'
import { IncidentTypeLabels, TYPE_COLORS } from '../utils/types'

const JAIPUR_CENTER = [26.9124, 75.7873]
const JAIPUR_BOUNDS = [[26.7, 75.5], [27.1, 76.1]]

const INCIDENT_ICONS = {
  violence: Activity,
  fall: MapPin,
  women_safety: Shield,
  snatch: Video,
  fire: Flame,
  crash: Car,
  other: AlertTriangle,
}

export function MapView() {
  const { incidents, heatmap, isLoading } = useIncidents()
  const [selectedIncident, setSelectedIncident] = useState(null)
  const [visibleTypes, setVisibleTypes] = useState(Object.keys(INCIDENT_ICONS))
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [mapZoom, setMapZoom] = useState(11)
  const [mapCenter, setMapCenter] = useState(JAIPUR_CENTER)
  const mapRef = useRef(null)

  const filteredIncidents = incidents.filter(i => visibleTypes.includes(i.incident_type))

  const handleTypeToggle = (type) => {
    setVisibleTypes(prev => 
      prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
    )
  }

  const handleZoomIn = () => {
    if (mapRef.current) {
      const newZoom = Math.min(mapZoom + 1, 18)
      setMapZoom(newZoom)
      mapRef.current.leafletElement.setZoom(newZoom)
    }
  }

  const handleZoomOut = () => {
    if (mapRef.current) {
      const newZoom = Math.max(mapZoom - 1, 8)
      setMapZoom(newZoom)
      mapRef.current.leafletElement.setZoom(newZoom)
    }
  }

  const handleResetView = () => {
    if (mapRef.current) {
      setMapZoom(11)
      setMapCenter(JAIPUR_CENTER)
      mapRef.current.leafletElement.setView(JAIPUR_CENTER, 11)
    }
  }

  useEffect(() => {
    if (mapRef.current && selectedIncident) {
      mapRef.current.leafletElement.setView(
        [selectedIncident.location.latitude, selectedIncident.location.longitude],
        15
      )
    }
  }, [selectedIncident])

  return (
    <div className="h-[calc(100vh-200px)] min-h-[600px] relative">
      {/* Map Controls */}
      <div className="absolute top-4 left-4 right-4 z-10 flex flex-col sm:flex-row gap-3 justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-lg font-semibold text-command-text hidden sm:block">Incident Map</h2>
          <div className="flex items-center gap-1 bg-command-panel/95 backdrop-blur-sm border border-command-border rounded-lg p-1">
            {Object.entries(INCIDENT_ICONS).map(([type, Icon]) => (
              <button
                key={type}
                onClick={() => handleTypeToggle(type)}
                className={classNames(
                  'p-2 rounded transition-colors relative',
                  visibleTypes.includes(type)
                    ? 'bg-command-accent/20 text-command-accent'
                    : 'text-command-text-dim hover:text-command-text hover:bg-command-panel-hover'
                )}
                title={IncidentTypeLabels[type]}
              >
                <Icon className="w-4 h-4" />
                {!visibleTypes.includes(type) && (
                  <span className="absolute -top-1 -right-1 w-3 h-3 bg-command-text-dim/50 rounded-full" />
                )}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-command-text-dim cursor-pointer">
            <input
              type="checkbox"
              checked={showHeatmap}
              onChange={(e) => setShowHeatmap(e.target.checked)}
              className="w-4 h-4 rounded border-command-border bg-command-panel text-command-accent focus:ring-command-accent"
            />
            Heatmap
          </label>
          <div className="flex items-center gap-1 bg-command-panel/95 backdrop-blur-sm border border-command-border rounded-lg p-1">
            <button onClick={handleZoomOut} className="p-2 rounded hover:bg-command-panel-hover text-command-text-muted" aria-label="Zoom out">
              <ZoomOut className="w-4 h-4" />
            </button>
            <button onClick={handleZoomIn} className="p-2 rounded hover:bg-command-panel-hover text-command-text-muted" aria-label="Zoom in">
              <ZoomIn className="w-4 h-4" />
            </button>
            <button onClick={handleResetView} className="p-2 rounded hover:bg-command-panel-hover text-command-text-muted" aria-label="Reset view">
              <Home className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Map */}
      <div className="absolute inset-0">
        <MapContainer
          ref={mapRef}
          center={mapCenter}
          zoom={mapZoom}
          maxBounds={JAIPUR_BOUNDS}
          maxZoom={18}
          minZoom={8}
          className="h-full w-full"
          style={{ background: '#0a0f1a' }}
          onMoveend={(e) => {
            const center = e.target.getCenter()
            const zoom = e.target.getZoom()
            setMapCenter([center.lat, center.lng])
            setMapZoom(zoom)
          }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />

          {/* Heatmap Layer */}
          {showHeatmap && heatmap.length > 0 && (
            <LayerGroup>
              {heatmap.map((point, index) => (
                <CircleMarker
                  key={`heat-${index}`}
                  center={[point.latitude, point.longitude]}
                  radius={Math.max(8, point.weight * 8)}
                  pathOptions={{
                    color: TYPE_COLORS[point.incident_type] || '#8b99b3',
                    fillColor: TYPE_COLORS[point.incident_type] || '#8b99b3',
                    fillOpacity: 0.15,
                    weight: 0,
                  }}
                />
              ))}
            </LayerGroup>
          )}

          {/* Incident Markers */}
          <LayerGroup>
            {filteredIncidents.map((incident) => (
              <IncidentMarker
                key={incident.incident_id}
                incident={incident}
                selected={selectedIncident?.incident_id === incident.incident_id}
                onClick={() => setSelectedIncident(incident)}
              />
            ))}
          </LayerGroup>
        </MapContainer>
      </div>

      {/* Selected Incident Panel */}
      {selectedIncident && (
        <div className="absolute bottom-4 left-4 right-4 sm:right-auto sm:w-80 z-10 animate-in">
          <IncidentMapPanel 
            incident={selectedIncident} 
            onClose={() => setSelectedIncident(null)} 
          />
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-4 left-4 z-10 bg-command-panel/95 backdrop-blur-sm border border-command-border rounded-lg p-3 shadow-panel max-w-xs">
        <div className="font-medium text-command-text mb-2">Legend</div>
        <div className="space-y-1.5 text-sm">
          {visibleTypes.map(type => (
            <div key={type} className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: TYPE_COLORS[type] }} />
              <span className="text-command-text-dim capitalize">{IncidentTypeLabels[type]}</span>
            </div>
          ))}
          {showHeatmap && (
            <div className="flex items-center gap-2 border-t border-command-border pt-2">
              <div className="w-3 h-3 rounded-full bg-command-accent/30 border border-command-accent" />
              <span className="text-command-text-dim">Heatmap Intensity</span>
            </div>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="absolute bottom-4 right-4 z-10 bg-command-panel/95 backdrop-blur-sm border border-command-border rounded-lg p-3 shadow-panel">
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-2xl font-bold text-command-accent">{filteredIncidents.length}</p>
            <p className="text-xs text-command-text-dim">Visible</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-command-danger">
              {filteredIncidents.filter(i => i.severity === 'critical').length}
            </p>
            <p className="text-xs text-command-text-dim">Critical</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-command-warning">
              {filteredIncidents.filter(i => i.status === 'new').length}
            </p>
            <p className="text-xs text-command-text-dim">New</p>
          </div>
        </div>
      </div>
    </div>
  )
}

function IncidentMarker({ incident, selected, onClick }) {
  const TypeIcon = INCIDENT_ICONS[incident.incident_type] || AlertTriangle
  const color = TYPE_COLORS[incident.incident_type] || '#8b99b3'

  return (
    <CircleMarker
      center={[incident.location.latitude, incident.location.longitude]}
      radius={selected ? 14 : incident.severity === 'critical' ? 12 : incident.severity === 'high' ? 10 : 8}
      pathOptions={{
        color: selected ? '#00d4aa' : color,
        fillColor: color,
        fillOpacity: 0.8,
        weight: selected ? 3 : 2,
        opacity: 1,
      }}
      onClick={onClick}
    >
      <Popup
        offset={[0, -12]}
        className="leaflet-popup-custom"
      >
        <IncidentPopupContent incident={incident} />
      </Popup>
    </CircleMarker>
  )
}

function IncidentPopupContent({ incident }) {
  const TypeIcon = INCIDENT_ICONS[incident.incident_type] || AlertTriangle
  const color = TYPE_COLORS[incident.incident_type] || '#8b99b3'

  return (
    <div className="p-2 min-w-[240px]">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${color}20` }}>
          <TypeIcon className="w-4 h-4" style={{ color }} />
        </div>
        <div>
          <p className="font-medium text-command-text">{IncidentTypeLabels[incident.incident_type]}</p>
          <p className="text-xs text-command-text-dim font-mono">{incident.incident_id.slice(0, 8)}</p>
        </div>
      </div>
      <div className="space-y-1 text-sm">
        <div className="flex justify-between">
          <span className="text-command-text-dim">Severity</span>
          <span className="font-medium text-command-text capitalize">{incident.severity}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-command-text-dim">Status</span>
          <span className="font-medium text-command-text capitalize">{incident.status.replace('_', ' ')}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-command-text-dim">Confidence</span>
          <span className="font-medium text-command-text font-mono">{Math.round(incident.confidence * 100)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-command-text-dim">Time</span>
          <span className="font-medium text-command-text font-mono">{new Date(incident.timestamp).toLocaleTimeString()}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-command-text-dim">Camera</span>
          <span className="font-medium text-command-text">{incident.location.camera_id}</span>
        </div>
      </div>
    </div>
  )
}

function IncidentMapPanel({ incident, onClose }) {
  const TypeIcon = INCIDENT_ICONS[incident.incident_type] || AlertTriangle
  const color = TYPE_COLORS[incident.incident_type] || '#8b99b3'
  const severityClass = incident.severity === 'critical' ? 'text-command-danger' : 
    incident.severity === 'high' ? 'text-command-warning' : 
    incident.severity === 'medium' ? 'text-command-info' : 'text-command-text-dim'

  return (
    <div className="card overflow-hidden">
      <div className="flex items-start justify-between p-4 border-b border-command-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${color}20` }}>
            <TypeIcon className="w-5 h-5" style={{ color }} />
          </div>
          <div>
            <h3 className="font-semibold text-command-text">{IncidentTypeLabels[incident.incident_type]}</h3>
            <span className={`badge ${severityClass} bg-opacity-20`}>{incident.severity}</span>
          </div>
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-command-panel-hover text-command-text-muted">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 space-y-3 max-h-64 overflow-y-auto">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Detail label="Incident ID" value={incident.incident_id.slice(0, 8)} monospace />
          <Detail label="Camera" value={incident.location.camera_id} />
          <Detail label="Location" value={incident.location.address} />
          <Detail label="Coordinates" value={`${incident.location.latitude.toFixed(4)}, ${incident.location.longitude.toFixed(4)}`} monospace />
          <Detail label="Time" value={new Date(incident.timestamp).toLocaleString()} />
          <Detail label="Confidence" value={`${Math.round(incident.confidence * 100)}%`} />
          <Detail label="Status" value={incident.status.replace('_', ' ')} />
        </div>

        {incident.evidence_clip && (
          <div className="p-3 bg-command-panel-hover rounded-lg border border-command-border">
            <p className="text-sm font-medium text-command-text mb-2">Evidence Clip</p>
            <video
              src={`/api/v1/evidence/${incident.evidence_clip.video_path.split('/').pop()}`}
              controls
              className="w-full rounded-lg bg-black"
            />
          </div>
        )}

        <div className="flex gap-2 pt-2">
          <button className="btn-primary flex-1">
            <Play className="w-4 h-4" />
            Review Evidence
          </button>
          <button className="btn-secondary">
            <MapPin className="w-4 h-4" />
            Directions
          </button>
        </div>
      </div>
    </div>
  )
}

function Detail({ label, value, monospace = false }) {
  return (
    <div className="p-2 bg-command-panel-hover rounded-lg border border-command-border">
      <p className="text-xs text-command-text-dim">{label}</p>
      <p className={classNames('font-medium text-command-text', monospace && 'font-mono text-xs')}>
        {value}
      </p>
    </div>
  )
}

export default MapView