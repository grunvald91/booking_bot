import { useState, useEffect, useMemo } from 'react'
import {
  Calendar,
  Wallet,
  Receipt,
  Activity,
  TrendingUp,
  TrendingDown,
  Scissors,
  User,
} from 'lucide-react'
import { api, type AnalyticsOverview, type AnalyticsDailyPoint } from '../../api/client'
import { useAdminBusiness } from '../../hooks/useAdminBusiness'
import { BusinessSelector } from '../../components/BusinessSelector'
import { AdminShell } from '../../components/AdminShell'

// ── Helpers ──
const PERIOD_DAYS: Record<string, number> = { week: 7, month: 30, year: 365 }

function formatRub(n: number): string {
  return `${new Intl.NumberFormat('ru-RU').format(Math.round(n))} ₽`
}

function aggregateByWeek(daily: AnalyticsDailyPoint[]): AnalyticsDailyPoint[] {
  const weeks: AnalyticsDailyPoint[] = []
  for (let i = 0; i < daily.length; i += 7) {
    const slice = daily.slice(i, i + 7)
    weeks.push({
      date: slice[0].date,
      bookings: slice.reduce((s, d) => s + d.bookings, 0),
      revenue: slice.reduce((s, d) => s + d.revenue, 0),
    })
  }
  return weeks
}

// ── Delta badge ──
function Delta({ cur, prev, isPoints }: { cur: number; prev: number; isPoints?: boolean }) {
  if (cur === 0 && prev === 0) return null
  let value: number
  let label: string
  if (isPoints) {
    value = cur - prev
    label = `${value >= 0 ? '+' : ''}${value.toFixed(1)} п.п.`
  } else if (prev === 0 && cur > 0) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 10, fontWeight: 600, color: 'var(--s-success)' }}>
        <TrendingUp size={10} /> новое
      </span>
    )
  } else {
    value = ((cur - prev) / prev) * 100
    label = `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
  }
  const positive = value >= 0
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 10, fontWeight: 600, color: positive ? 'var(--s-success)' : 'var(--s-danger)' }}>
      {positive ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
      {label}
    </span>
  )
}

// ── KPI card ──
function KpiCard({ label, value, icon, color, cur, prev, isPoints }: {
  label: string; value: string; icon: React.ReactNode; color: string; cur: number; prev: number; isPoints?: boolean
}) {
  return (
    <div className="ds-card" style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="ds-sub">{label}</span>
        <span style={{ width: 32, height: 32, borderRadius: 9, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'var(--s-accent-soft)', color }}>
          {icon}
        </span>
      </div>
      <p style={{ fontSize: 20, fontWeight: 750, color: 'var(--s-text)', lineHeight: 1.1, margin: 0 }}>{value}</p>
      <Delta cur={cur} prev={prev} isPoints={isPoints} />
    </div>
  )
}

// ── Bar + line chart ──
function DailyChart({ daily }: { daily: AnalyticsDailyPoint[] }) {
  const points = useMemo(() => (daily.length > 60 ? aggregateByWeek(daily) : daily), [daily])
  const maxBookings = points.length > 0 ? Math.max(...points.map((p) => p.bookings), 1) : 1
  const maxRevenue = points.length > 0 ? Math.max(...points.map((p) => p.revenue), 1) : 1
  const labelStep = points.length > 30 ? 5 : points.length > 14 ? 2 : 1

  if (points.length === 0) {
    return <div className="ds-sub" style={{ textAlign: 'center', padding: '40px 0' }}>Нет данных за выбранный период</div>
  }

  const n = points.length
  const linePoints = points.map((p, i) => ({ x: i + 0.5, y: 100 - (p.revenue / maxRevenue) * 100 }))
  const pathD = linePoints.map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(3)} ${pt.y.toFixed(2)}`).join(' ')
  const needsScroll = n > 14
  const innerStyle = needsScroll ? { minWidth: `${n * 22}px` } : undefined

  return (
    <div style={{ position: 'relative' }}>
      <div className="scrollbar-hide" style={{ overflowX: 'auto' }}>
        <div style={innerStyle}>
          <div style={{ position: 'relative', height: 160 }}>
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'flex-end', gap: 2 }}>
              {points.map((p, i) => (
                <div key={`bar-${i}`} style={{ flex: 1, minWidth: 14, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
                  <span style={{ fontSize: 9, color: 'var(--s-muted)', fontWeight: 600, lineHeight: 1 }}>{p.bookings > 0 ? p.bookings : ''}</span>
                  <div style={{ width: '100%', height: `${Math.max((p.bookings / maxBookings) * 100, 2)}%`, minHeight: 3, background: 'var(--s-accent)', borderRadius: '4px 4px 0 0' }} />
                </div>
              ))}
            </div>
            <svg viewBox={`0 0 ${n} 100`} preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', color: 'var(--s-warning)' }}>
              <path d={pathD} fill="none" strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" stroke="currentColor" />
              {linePoints.map((pt, i) => (
                <circle key={`pt-${i}`} cx={pt.x} cy={pt.y} r="2" vectorEffect="non-scaling-stroke" fill="currentColor" />
              ))}
            </svg>
          </div>
          <div style={{ display: 'flex', gap: 2, marginTop: 4 }}>
            {points.map((p, i) => {
              const d = new Date(p.date)
              const label = `${d.getDate()}.${String(d.getMonth() + 1).padStart(2, '0')}`
              return (
                <span key={`lbl-${i}`} style={{ flex: 1, minWidth: 14, textAlign: 'center', fontSize: 8, color: 'var(--s-muted)', lineHeight: 1, visibility: i % labelStep === 0 ? 'visible' : 'hidden' }}>{label}</span>
              )
            })}
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 12, justifyContent: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 12, height: 12, borderRadius: 3, background: 'var(--s-accent)' }} />
          <span className="ds-caption">Записи</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 20, height: 2, borderRadius: 2, background: 'var(--s-warning)' }} />
          <span className="ds-caption">Выручка</span>
        </div>
      </div>
    </div>
  )
}

// ── Top list ──
interface TopItem { id: number; name: string; count: number; revenue: number; share_percent: number }

function TopCard({ title, icon, items }: { title: string; icon: React.ReactNode; items: TopItem[] }) {
  return (
    <div className="ds-card" style={{ padding: 14 }}>
      <h3 className="ds-h3" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>{icon}{title}</h3>
      {items.length === 0 ? (
        <p className="ds-sub" style={{ textAlign: 'center', padding: '16px 0' }}>Нет данных за период</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {items.map((item) => (
            <div key={item.id}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--s-text)', maxWidth: '55%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</span>
                <span className="ds-caption" style={{ whiteSpace: 'nowrap' }}>{item.count} зап. · {formatRub(item.revenue)} ({item.share_percent.toFixed(0)}%)</span>
              </div>
              <div style={{ height: 4, background: 'var(--s-surface-3)', borderRadius: 999, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${item.share_percent}%`, background: 'var(--s-accent)', borderRadius: 999 }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main ──
export function AnalyticsPage() {
  const { businesses, selectedId: businessId, selectBusiness } = useAdminBusiness()
  const [data, setData] = useState<AnalyticsOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState<'week' | 'month' | 'year'>('week')

  useEffect(() => {
    if (!businessId) return
    setLoading(true)
    api.getAnalyticsOverview(businessId, PERIOD_DAYS[period]).then(setData).catch(() => setData(null)).finally(() => setLoading(false))
  }, [businessId, period])

  const periods = [
    { value: 'week' as const, label: 'Неделя' },
    { value: 'month' as const, label: 'Месяц' },
    { value: 'year' as const, label: 'Год' },
  ]
  const kpis = data?.kpis

  return (
    <AdminShell
      title="Аналитика"
      headerExtra={<BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} />}
    >
      {/* Период */}
      <div className="ds-seg ds-seg--full" style={{ marginTop: 4, marginBottom: 14 }}>
        {periods.map((p) => (
          <button key={p.value} className={period === p.value ? 'on' : ''} onClick={() => setPeriod(p.value)}>{p.label}</button>
        ))}
      </div>

      {loading ? (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {[1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 92, borderRadius: 14 }} />)}
          </div>
          <div className="skeleton" style={{ height: 210, borderRadius: 14, marginTop: 14 }} />
        </div>
      ) : (
        <>
          {/* KPI */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <KpiCard label="Выручка" value={kpis ? formatRub(kpis.revenue) : '—'} icon={<Wallet size={16} />} color="var(--s-accent)" cur={kpis?.revenue ?? 0} prev={kpis?.revenue_prev ?? 0} />
            <KpiCard label="Записей" value={kpis ? String(kpis.bookings) : '—'} icon={<Calendar size={16} />} color="var(--s-success)" cur={kpis?.bookings ?? 0} prev={kpis?.bookings_prev ?? 0} />
            <KpiCard label="Средний чек" value={kpis ? formatRub(kpis.avg_check) : '—'} icon={<Receipt size={16} />} color="var(--s-warning)" cur={kpis?.avg_check ?? 0} prev={kpis?.avg_check_prev ?? 0} />
            <KpiCard label="Загрузка" value={kpis && kpis.load_percent != null ? `${kpis.load_percent.toFixed(1)}%` : '—'} icon={<Activity size={16} />} color="var(--s-danger)" cur={kpis?.load_percent ?? 0} prev={kpis?.load_percent_prev ?? 0} isPoints />
          </div>

          {/* График */}
          <div className="ds-card" style={{ padding: 14, marginTop: 14 }}>
            <h2 className="ds-h3" style={{ marginBottom: 14 }}>Записи и выручка по дням</h2>
            <DailyChart daily={data?.daily ?? []} />
          </div>

          {/* Топы */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 12 }}>
            <TopCard title="Топ услуг" icon={<Scissors size={14} style={{ color: 'var(--s-accent)' }} />} items={data?.top_services ?? []} />
            <TopCard title="Топ сотрудников" icon={<User size={14} style={{ color: 'var(--s-accent)' }} />} items={data?.top_employees ?? []} />
          </div>
        </>
      )}
    </AdminShell>
  )
}
