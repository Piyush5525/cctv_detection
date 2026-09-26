import { classNames } from '../utils/format'

export function KPICard({ value, label, icon: Icon, iconColor, trend, trendUp, format }) {
  const displayValue = format ? format(value) : value.toLocaleString()

  return (
    <div className="kpi-card" style={{ '--accent-color': iconColor.replace('text-', '') }}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-command-text-dim mb-1">{label}</p>
          <p className="text-2xl lg:text-3xl font-bold text-command-text tabular-nums">
            {displayValue}
          </p>
          {trend && (
            <div className="flex items-center gap-1 mt-2">
              <span className={classNames(
                'text-xs font-medium',
                trendUp ? 'text-command-accent' : 'text-command-danger'
              )}>
                {trend}
              </span>
              <span className="text-xs text-command-text-dim">vs last period</span>
            </div>
          )}
        </div>
        <div className="w-12 h-12 rounded-xl bg-command-panel-hover flex items-center justify-center flex-shrink-0">
          <Icon className="w-6 h-6" style={{ color: iconColor.replace('text-', '') }} />
        </div>
      </div>
    </div>
  )
}