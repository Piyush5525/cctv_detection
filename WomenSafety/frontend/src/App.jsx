import { Routes, Route, Navigate } from 'react-router-dom'
import { DashboardLayout } from './components/Layout'
import MapView from './pages/MapView'
import { WebSocketProvider } from './context/WebSocketContext'

function App() {
  return (
      <WebSocketProvider>
        <Routes>
          <Route path="/" element={<DashboardLayout />}>
            <Route index element={<Navigate to="/map" replace />} />
            <Route path="map" element={<MapView />} />
            <Route path="*" element={<Navigate to="/map" replace />} />
          </Route>
        </Routes>
      </WebSocketProvider>
  )
}

export default App