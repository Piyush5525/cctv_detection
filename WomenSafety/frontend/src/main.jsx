import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 4000,
          style: {
            background: '#111827',
            color: '#e8edf5',
            border: '1px solid #1f2a44',
            borderRadius: '12px',
            padding: '14px 16px',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5)',
          },
          success: {
            iconTheme: {
              primary: '#00d4aa',
              secondary: '#0a0f1a',
            },
          },
          error: {
            iconTheme: {
              primary: '#ff4757',
              secondary: '#0a0f1a',
            },
          },
        }}
      />
    </BrowserRouter>
  </React.StrictMode>
)