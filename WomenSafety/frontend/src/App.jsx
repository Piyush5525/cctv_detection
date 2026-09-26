import { Routes, Route, Navigate } from 'react-router-dom'
import { DashboardLayout } from './components/Layout'
import Dashboard from './pages/Dashboard'
import LiveIncidents from './pages/LiveIncidents'
import MapView from './pages/MapView'
import EvidenceGallery from './pages/EvidenceGallery'
import Analytics from './pages/Analytics'
import Settings from './pages/Settings'
import { IncidentProvider } from './context/IncidentContext'
import { WebSocketProvider } from './context/WebSocketContext'

function App() {
  return (
    <IncidentProvider>
      <WebSocketProvider>
        <Routes>
          <Route path="/" element={<DashboardLayout />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="incidents" element={<LiveIncidents />} />
            <Route path="map" element={<MapView />} />
            <Route path="evidence" element={<EvidenceGallery />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </WebSocketProvider>
    </IncidentProvider>
  )
}

export default App