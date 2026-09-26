import { useState } from 'react'
import { 
  Save, 
  RotateCcw,
  Shield,
  Bell,
  Database,
  Cpu,
  Wifi,
  User,
  Key,
  ToggleLeft,
  ToggleRight,
  Eye,
  EyeOff,
  Download,
  Upload,
  Trash2,
  AlertTriangle,
  CheckCircle,
} from 'lucide-react'
import { useIncidents } from '../context/IncidentContext'
import { classNames } from '../utils/format'

const SETTINGS_SECTIONS = [
  { id: 'general', label: 'General', icon: Shield },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'detection', label: 'Detection', icon: Cpu },
  { id: 'storage', label: 'Storage', icon: Database },
  { id: 'network', label: 'Network', icon: Wifi },
  { id: 'security', label: 'Security', icon: Key },
]

export function Settings() {
  const { refetch } = useIncidents()
  const [activeSection, setActiveSection] = useState('general')
  const [saved, setSaved] = useState(false)

  const [settings, setSettings] = useState({
    general: {
      timezone: 'Asia/Kolkata',
      language: 'en',
      dateFormat: 'DD/MM/YYYY',
      timeFormat: '24h',
      autoRefresh: true,
      refreshInterval: 30,
      theme: 'dark',
    },
    notifications: {
      emailAlerts: true,
      smsAlerts: false,
      pushNotifications: true,
      criticalOnly: false,
      soundEnabled: true,
      cooldownMinutes: 5,
    },
    detection: {
      violenceEnabled: true,
      fallEnabled: true,
      snatchEnabled: true,
      fireEnabled: true,
      crashEnabled: true,
      confidenceThreshold: 0.5,
      maxConcurrentStreams: 4,
      gpuAcceleration: true,
    },
    storage: {
      evidenceRetentionDays: 30,
      maxEvidenceSizeGB: 10,
      autoCleanup: true,
      compressionEnabled: true,
      backupEnabled: false,
      backupPath: '/mnt/backup',
    },
    network: {
      apiPort: 8000,
      wsPort: 8001,
      corsEnabled: true,
      rateLimit: 100,
      sslEnabled: false,
      allowedOrigins: '*',
    },
    security: {
      apiKeyEnabled: true,
      jwtExpiryHours: 24,
      passwordMinLength: 12,
      twoFactorEnabled: false,
      sessionTimeoutMinutes: 60,
      auditLogging: true,
    },
  })

  const handleChange = (section, key, value) => {
    setSettings(prev => ({
      ...prev,
      [section]: { ...prev[section], [key]: value }
    }))
    setSaved(false)
  }

  const handleSave = async () => {
    // Save to localStorage or backend
    localStorage.setItem('dashboard_settings', JSON.stringify(settings))
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  const handleReset = (section) => {
    // Reset to defaults
  }

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(settings, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'dashboard-settings.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleImport = (e) => {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const imported = JSON.parse(event.target.result)
        setSettings(prev => ({ ...prev, ...imported }))
      } catch (err) {
        console.error('Failed to import settings:', err)
      }
    }
    reader.readAsText(file)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-command-text">Settings</h1>
          <p className="text-command-text-dim mt-1">Configure dashboard behavior and detection parameters</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-secondary" onClick={handleExport}>
            <Download className="w-4 h-4" />
            Export
          </button>
          <label className="btn-secondary cursor-pointer">
            <Upload className="w-4 h-4" />
            Import
            <input type="file" accept=".json" onChange={handleImport} className="hidden" />
          </label>
          <button 
            onClick={handleSave}
            className={classNames('btn-primary', saved && 'bg-command-accent/50')}
            disabled={saved}
          >
            <Save className="w-4 h-4" />
            {saved ? 'Saved' : 'Save Changes'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Sidebar Navigation */}
        <div className="lg:col-span-1">
          <div className="card sticky top-24 h-fit">
            <nav className="space-y-1" role="navigation" aria-label="Settings sections">
              {SETTINGS_SECTIONS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setActiveSection(id)}
                  className={classNames(
                    'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 text-left',
                    activeSection === id
                      ? 'bg-command-accent/10 text-command-accent border border-command-accent/30'
                      : 'text-command-text-muted hover:text-command-text hover:bg-command-panel-hover'
                  )}
                  role="tab"
                  aria-selected={activeSection === id}
                >
                  <Icon className="w-5 h-5 flex-shrink-0" />
                  <span>{label}</span>
                </button>
              ))}
            </nav>

            <div className="mt-6 pt-6 border-t border-command-border">
              <div className="flex items-center gap-3 p-3 rounded-lg bg-command-panel-hover">
                <div className="w-8 h-8 rounded-lg bg-command-accent/20 flex items-center justify-center">
                  <CheckCircle className="w-4 h-4 text-command-accent" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-command-text">All systems operational</p>
                  <p className="text-xs text-command-text-dim">Last checked: Just now</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Settings Content */}
        <div className="lg:col-span-3">
          <div className="card">
            <div className="p-6 border-b border-command-border">
              <h2 className="text-lg font-semibold text-command-text capitalize">
                {SETTINGS_SECTIONS.find(s => s.id === activeSection)?.label} Settings
              </h2>
            </div>
            <div className="p-6">
              {activeSection === 'general' && <GeneralSettings settings={settings.general} onChange={(k, v) => handleChange('general', k, v)} />}
              {activeSection === 'notifications' && <NotificationSettings settings={settings.notifications} onChange={(k, v) => handleChange('notifications', k, v)} />}
              {activeSection === 'detection' && <DetectionSettings settings={settings.detection} onChange={(k, v) => handleChange('detection', k, v)} />}
              {activeSection === 'storage' && <StorageSettings settings={settings.storage} onChange={(k, v) => handleChange('storage', k, v)} />}
              {activeSection === 'network' && <NetworkSettings settings={settings.network} onChange={(k, v) => handleChange('network', k, v)} />}
              {activeSection === 'security' && <SecuritySettings settings={settings.security} onChange={(k, v) => handleChange('security', k, v)} />}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function SettingRow({ label, description, children }) {
  return (
    <div className="py-4 border-b border-command-border/50 last:border-0">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex-1">
          <label className="block text-sm font-medium text-command-text">{label}</label>
          {description && <p className="text-xs text-command-text-dim mt-0.5">{description}</p>}
        </div>
        <div className="flex items-center gap-2">{children}</div>
      </div>
    </div>
  )
}

function Toggle({ checked, onChange, disabled }) {
  return (
    <button
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      className={classNames(
        'relative w-11 h-6 rounded-full transition-colors duration-200 flex items-center p-0.5',
        checked ? 'bg-command-accent' : 'bg-command-panel-hover border border-command-border'
      )}
      role="switch"
      aria-checked={checked}
    >
      <span className={classNames(
        'w-5 h-5 rounded-full bg-white shadow-md transition-transform duration-200 flex items-center justify-center',
        checked ? 'translate-x-full' : 'translate-x-0'
      )}>
        {checked ? <ToggleRight className="w-3 h-3 text-command-accent" /> : <ToggleLeft className="w-3 h-3 text-command-text-dim" />}
      </span>
    </button>
  )
}

function GeneralSettings({ settings, onChange }) {
  return (
    <div className="space-y-2">
      <SettingRow label="Timezone" description="Dashboard timezone for timestamps">
        <select value={settings.timezone} onChange={e => onChange('timezone', e.target.value)} className="input w-auto text-sm">
          <option value="Asia/Kolkata">Asia/Kolkata (IST)</option>
          <option value="UTC">UTC</option>
          <option value="America/New_York">America/New_York (EST)</option>
          <option value="Europe/London">Europe/London (GMT)</option>
        </select>
      </SettingRow>
      <SettingRow label="Language" description="Interface language">
        <select value={settings.language} onChange={e => onChange('language', e.target.value)} className="input w-auto text-sm">
          <option value="en">English</option>
          <option value="hi">Hindi</option>
        </select>
      </SettingRow>
      <SettingRow label="Date Format" description="Date display format">
        <select value={settings.dateFormat} onChange={e => onChange('dateFormat', e.target.value)} className="input w-auto text-sm">
          <option value="DD/MM/YYYY">DD/MM/YYYY</option>
          <option value="MM/DD/YYYY">MM/DD/YYYY</option>
          <option value="YYYY-MM-DD">YYYY-MM-DD</option>
        </select>
      </SettingRow>
      <SettingRow label="Time Format" description="Time display format">
        <select value={settings.timeFormat} onChange={e => onChange('timeFormat', e.target.value)} className="input w-auto text-sm">
          <option value="24h">24 Hour</option>
          <option value="12h">12 Hour</option>
        </select>
      </SettingRow>
      <SettingRow label="Auto Refresh" description="Automatically refresh incident data">
        <Toggle checked={settings.autoRefresh} onChange={v => onChange('autoRefresh', v)} />
      </SettingRow>
      <SettingRow label="Refresh Interval (seconds)" description="How often to poll for new data">
        <input
          type="number"
          min="10"
          max="300"
          value={settings.refreshInterval}
          onChange={e => onChange('refreshInterval', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="Theme" description="Color theme (dark mode only for command center)">
        <select value={settings.theme} onChange={e => onChange('theme', e.target.value)} className="input w-auto text-sm" disabled>
          <option value="dark">Dark (Command Center)</option>
        </select>
      </SettingRow>
    </div>
  )
}

function NotificationSettings({ settings, onChange }) {
  return (
    <div className="space-y-2">
      <SettingRow label="Email Alerts" description="Send email notifications for incidents">
        <Toggle checked={settings.emailAlerts} onChange={v => onChange('emailAlerts', v)} />
      </SettingRow>
      <SettingRow label="SMS Alerts" description="Send SMS for critical incidents">
        <Toggle checked={settings.smsAlerts} onChange={v => onChange('smsAlerts', v)} />
      </SettingRow>
      <SettingRow label="Push Notifications" description="Browser push notifications">
        <Toggle checked={settings.pushNotifications} onChange={v => onChange('pushNotifications', v)} />
      </SettingRow>
      <SettingRow label="Critical Only" description="Only notify for critical severity incidents">
        <Toggle checked={settings.criticalOnly} onChange={v => onChange('criticalOnly', v)} />
      </SettingRow>
      <SettingRow label="Sound Enabled" description="Play alert sound for new incidents">
        <Toggle checked={settings.soundEnabled} onChange={v => onChange('soundEnabled', v)} />
      </SettingRow>
      <SettingRow label="Alert Cooldown (minutes)" description="Minimum time between repeated alerts">
        <input
          type="number"
          min="1"
          max="60"
          value={settings.cooldownMinutes}
          onChange={e => onChange('cooldownMinutes', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
    </div>
  )
}

function DetectionSettings({ settings, onChange }) {
  const detectors = [
    { key: 'violenceEnabled', label: 'Violence Detection', desc: 'CLIP-based violence classification' },
    { key: 'fallEnabled', label: 'Fall Detection', desc: 'Pose-based fall and health emergency detection' },
    { key: 'snatchEnabled', label: 'Snatch Detection', desc: 'Behavioral analysis for snatching incidents' },
    { key: 'fireEnabled', label: 'Fire Detection', desc: 'YOLO-based fire and smoke detection' },
    { key: 'crashEnabled', label: 'Crash Detection', desc: 'Vehicle accident detection' },
  ]

  return (
    <div className="space-y-2">
      {detectors.map(d => (
        <SettingRow key={d.key} label={d.label} description={d.desc}>
          <Toggle checked={settings[d.key]} onChange={v => onChange(d.key, v)} />
        </SettingRow>
      ))}
      <SettingRow label="Confidence Threshold" description="Minimum confidence for incident creation">
        <input
          type="range"
          min="0.1"
          max="0.9"
          step="0.05"
          value={settings.confidenceThreshold}
          onChange={e => onChange('confidenceThreshold', parseFloat(e.target.value))}
          className="w-48"
        />
        <span className="text-sm font-mono text-command-accent w-10">{settings.confidenceThreshold.toFixed(2)}</span>
      </SettingRow>
      <SettingRow label="Max Concurrent Streams" description="Maximum video streams to process simultaneously">
        <input
          type="number"
          min="1"
          max="16"
          value={settings.maxConcurrentStreams}
          onChange={e => onChange('maxConcurrentStreams', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="GPU Acceleration" description="Use GPU for inference (requires CUDA)">
        <Toggle checked={settings.gpuAcceleration} onChange={v => onChange('gpuAcceleration', v)} />
      </SettingRow>
    </div>
  )
}

function StorageSettings({ settings, onChange }) {
  return (
    <div className="space-y-2">
      <SettingRow label="Evidence Retention (days)" description="Days to keep evidence clips before auto-deletion">
        <input
          type="number"
          min="1"
          max="365"
          value={settings.evidenceRetentionDays}
          onChange={e => onChange('evidenceRetentionDays', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="Max Evidence Storage (GB)" description="Maximum disk space for evidence clips">
        <input
          type="number"
          min="1"
          max="1000"
          value={settings.maxEvidenceSizeGB}
          onChange={e => onChange('maxEvidenceSizeGB', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="Auto Cleanup" description="Automatically delete old evidence when limit reached">
        <Toggle checked={settings.autoCleanup} onChange={v => onChange('autoCleanup', v)} />
      </SettingRow>
      <SettingRow label="Compression" description="Compress evidence clips to save space">
        <Toggle checked={settings.compressionEnabled} onChange={v => onChange('compressionEnabled', v)} />
      </SettingRow>
      <SettingRow label="Backup Enabled" description="Backup evidence to secondary storage">
        <Toggle checked={settings.backupEnabled} onChange={v => onChange('backupEnabled', v)} />
      </SettingRow>
      <SettingRow label="Backup Path" description="Directory for evidence backups">
        <input
          type="text"
          value={settings.backupPath}
          onChange={e => onChange('backupPath', e.target.value)}
          className="input w-full max-w-md text-sm font-mono"
        />
      </SettingRow>
    </div>
  )
}

function NetworkSettings({ settings, onChange }) {
  return (
    <div className="space-y-2">
      <SettingRow label="API Port" description="HTTP API server port">
        <input
          type="number"
          min="1024"
          max="65535"
          value={settings.apiPort}
          onChange={e => onChange('apiPort', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="WebSocket Port" description="WebSocket server port">
        <input
          type="number"
          min="1024"
          max="65535"
          value={settings.wsPort}
          onChange={e => onChange('wsPort', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="CORS Enabled" description="Allow cross-origin requests">
        <Toggle checked={settings.corsEnabled} onChange={v => onChange('corsEnabled', v)} />
      </SettingRow>
      <SettingRow label="Rate Limit (req/min)" description="API rate limiting">
        <input
          type="number"
          min="10"
          max="1000"
          value={settings.rateLimit}
          onChange={e => onChange('rateLimit', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="SSL/TLS Enabled" description="Enable HTTPS/WSS (requires certificates)">
        <Toggle checked={settings.sslEnabled} onChange={v => onChange('sslEnabled', v)} disabled />
      </SettingRow>
      <SettingRow label="Allowed Origins" description="Comma-separated list of allowed CORS origins">
        <input
          type="text"
          value={settings.allowedOrigins}
          onChange={e => onChange('allowedOrigins', e.target.value)}
          className="input w-full max-w-md text-sm font-mono"
        />
      </SettingRow>
    </div>
  )
}

function SecuritySettings({ settings, onChange }) {
  return (
    <div className="space-y-2">
      <SettingRow label="API Key Authentication" description="Require API key for all requests">
        <Toggle checked={settings.apiKeyEnabled} onChange={v => onChange('apiKeyEnabled', v)} />
      </SettingRow>
      <SettingRow label="JWT Expiry (hours)" description="Access token lifetime">
        <input
          type="number"
          min="1"
          max="168"
          value={settings.jwtExpiryHours}
          onChange={e => onChange('jwtExpiryHours', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="Min Password Length" description="Minimum password length for users">
        <input
          type="number"
          min="8"
          max="64"
          value={settings.passwordMinLength}
          onChange={e => onChange('passwordMinLength', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="Two-Factor Authentication" description="Require 2FA for admin accounts">
        <Toggle checked={settings.twoFactorEnabled} onChange={v => onChange('twoFactorEnabled', v)} disabled />
      </SettingRow>
      <SettingRow label="Session Timeout (minutes)" description="Auto-logout after inactivity">
        <input
          type="number"
          min="5"
          max="480"
          value={settings.sessionTimeoutMinutes}
          onChange={e => onChange('sessionTimeoutMinutes', parseInt(e.target.value))}
          className="input w-auto text-sm"
        />
      </SettingRow>
      <SettingRow label="Audit Logging" description="Log all administrative actions">
        <Toggle checked={settings.auditLogging} onChange={v => onChange('auditLogging', v)} />
      </SettingRow>
    </div>
  )
}

export default Settings