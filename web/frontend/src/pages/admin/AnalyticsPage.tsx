import { useState, useEffect, useMemo } from 'react'
import {
  BarChart3,
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

// ── Helpers ──────────────────────────────────────────────────────────────────

const PERIOD_DAYS: Record<string, number> = {
  week: 7,
  month: 30,
  year: 365,
}

function formatRub(n: number): string {
  return `${new Intl.NumberFormat('ru-RU').format(Math.round(n))} ₽`
}

// Aggregate daily points into weekly buckets (sum bookings + revenue, label = week start date)
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

// ── Delta badge ───────────────────────────────────────────────────────────────

interface DeltaProps {
  cur: number
  prev: number
  isPoints?: boolean // for load_percent: absolute diff in pp
}

function Delta({ cur, prev, isPoints }: DeltaProps) {
  if (cur === 0 && prev === 0) return null

  let value: number
  let label: string

  if (isPoints) {
    value = cur - prev
    const sign = value >= 0 ? '+' : ''
    label = `${sign}${value.toFixed(1)} п.п.`
  } else if (prev === 0 && cur > 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-apple-success text-[10px] font-medium">
        <TrendingUp size={10} />
        новое
      </span>
    )
  } else {
    value = ((cur - prev) / prev) * 100
    const sign = value >= 0 ? '+' : ''
    label = `${sign}${value.toFixed(1)}%`
  }

  const positive = value >= 0
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[10px] font-medium ${
        positive ? 'text-apple-success' : 'text-apple-danger'
      }`}
    >
      {positive ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
      {label}
    </span>
  )
}

// ── KPI card ──────────────────────────────────────────────────────────────────

interface KpiCardProps {
  label: string
  value: string
  icon: React.ReactNode
  iconBg: string
  cur: number
  prev: number
  isPoints?: boolean
}

function KpiCard({ label, value, icon, iconBg, cur, prev, isPoints }: KpiCardProps) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-apple-gray">{label}</p>
        <div className={`w-8 h-8 rounded-xl flex items-center justify-center ${iconBg}`}>
          {icon}
        </div>
      </div>
      <p className="text-xl font-bold text-apple-text leading-tight">{value}</p>
      <Delta cur={cur} prev={prev} isPoints={isPoints} />
    </div>
  )
}

// ── Bar+Line chart ────────────────────────────────────────────────────────────

interface ChartProps {
  daily: AnalyticsDailyPoint[]
}

function DailyChart({ daily }: ChartProps) {
  const points = useMemo(() => {
    if (daily.length > 60) return aggregateByWeek(daily)
    return daily
  }, [daily])

  const maxBookings = points.length > 0 ? Math.max(...points.map(p => p.bookings), 1) : 1
  const maxRevenue = points.length > 0 ? Math.max(...points.map(p => p.revenue), 1) : 1

  const labelStep = points.length > 30 ? 5 : points.length > 14 ? 2 : 1

  if (points.length === 0) {
    return (
      <div className="text-center py-10 text-apple-gray text-sm">
        Нет данных за выбранный период
      </div>
    )
  }

  const n = points.length
  // Each point is centered in its column. cx = i + 0.5 in viewBox units (0..n).
  // cy: 0 = top, 100 = bottom. Revenue 0 → cy=100, max → cy=0.
  const linePoints = points.map((p, i) => ({
    x: i + 0.5,
    y: 100 - (p.revenue / maxRevenue) * 100,
  }))
  const pathD = linePoints
    .map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(3)} ${pt.y.toFixed(2)}`)
    .join(' ')

  // Scroll horizontally when bars get too dense
  const needsScroll = n > 14
  const innerStyle = needsScroll ? { minWidth: `${n * 22}px` } : undefined

  return (
    <div className="relative">
      <div className="overflow-x-auto scrollbar-hide">
        <div style={innerStyle}>
          {/* Bar area + SVG overlay, same dimensions */}
          <div className="relative h-40">
            <div className="absolute inset-0 flex items-end gap-0.5">
              {points.map((p, i) => {
                const height = (p.bookings / maxBookings) * 100
                return (
                  <div
                    key={`bar-${i}`}
                    className="flex-1 min-w-[14px] flex flex-col items-center justify-end gap-0.5"
                  >
                    <span className="text-[9px] text-apple-gray font-medium leading-none">
                      {p.bookings > 0 ? p.bookings : ''}
                    </span>
                    <div
                      className="w-full bg-apple-blue/75 rounded-t-md hover:bg-apple-blue transition-colors min-h-[3px]"
                      style={{ height: `${Math.max(height, 2)}%` }}
                    />
                  </div>
                )
              })}
            </div>

            {/* SVG line — covers exactly bar area; non-scaling-stroke keeps thickness constant */}
            <svg
              viewBox={`0 0 ${n} 100`}
              preserveAspectRatio="none"
              className="absolute inset-0 w-full h-full pointer-events-none"
            >
              <path
                d={pathD}
                fill="none"
                strokeWidth="1.5"
                vectorEffect="non-scaling-stroke"
                strokeLinejoin="round"
                strokeLinecap="round"
                className="text-apple-warning"
                stroke="currentColor"
              />
              {linePoints.map((pt, i) => (
                <circle
                  key={`pt-${i}`}
                  cx={pt.x}
                  cy={pt.y}
                  r="2"
                  vectorEffect="non-scaling-stroke"
                  className="text-apple-warning"
                  fill="currentColor"
                />
              ))}
            </svg>
          </div>

          {/* X-axis labels — separate row, same column structure */}
          <div className="flex gap-0.5 mt-1">
            {points.map((p, i) => {
              const d = new Date(p.date)
              const label = `${d.getDate()}.${String(d.getMonth() + 1).padStart(2, '0')}`
              const showLabel = i % labelStep === 0
              return (
                <span
                  key={`lbl-${i}`}
                  className={`flex-1 min-w-[14px] text-center text-[8px] text-apple-gray leading-none ${
                    !showLabel ? 'invisible' : ''
                  }`}
                >
                  {label}
                </span>
              )
            })}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-3 justify-center">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-sm bg-apple-blue/75" />
          <span className="text-[10px] text-apple-gray">Записи</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-0.5 bg-apple-warning rounded" />
          <span className="text-[10px] text-apple-gray">Выручка</span>
        </div>
      </div>
    </div>
  )
}

// ── Top list (services / employees) ──────────────────────────────────────────

interface TopItem {
  id: number
  name: string
  count: number
  revenue: number
  share_percent: number
}

interface TopCardProps {
  title: string
  icon: React.ReactNode
  items: TopItem[]
}

function TopCard({ title, icon, items }: TopCardProps) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-4">
      <h3 className="font-semibold text-apple-text text-sm flex items-center gap-2 mb-3">
        {icon}
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="text-apple-gray text-xs text-center py-4">Нет данных за период</p>
      ) : (
        <div className="space-y-3">
          {items.map(item => (
            <div key={item.id}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-apple-text font-medium truncate max-w-[55%]">
                  {item.name}
                </span>
                <span className="text-[10px] text-apple-gray whitespace-nowrap">
                  {item.count} зап. · {formatRub(item.revenue)} ({item.share_percent.toFixed(0)}%)
                </span>
              </div>
              <div className="h-1 bg-apple-bg rounded-full overflow-hidden">
                <div
                  className="h-full bg-apple-blue rounded-full"
                  style={{ width: `${item.share_percent}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function AnalyticsPage() {
  const { businesses, selectedId: businessId, selectBusiness } = useAdminBusiness()
  const [data, setData] = useState<AnalyticsOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState<'week' | 'month' | 'year'>('week')

  useEffect(() => {
    if (!businessId) return
    setLoading(true)
    const days = PERIOD_DAYS[period]
    api
      .getAnalyticsOverview(businessId, days)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [businessId, period])

  const periods = [
    { value: 'week' as const, label: 'Неделя' },
    { value: 'month' as const, label: 'Месяц' },
    { value: 'year' as const, label: 'Год' },
  ]

  const kpis = data?.kpis

  // ── Skeleton ──
  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 skeleton mb-4" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="h-24 skeleton rounded-2xl" />
          <div className="h-24 skeleton rounded-2xl" />
          <div className="h-24 skeleton rounded-2xl" />
          <div className="h-24 skeleton rounded-2xl" />
        </div>
        <div className="h-52 skeleton rounded-2xl" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="h-40 skeleton rounded-2xl" />
          <div className="h-40 skeleton rounded-2xl" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} vertical />

      {/* Header */}
      <div className="flex items-center justify-between animate-fade-in">
        <h1 className="text-lg font-bold text-apple-text flex items-center gap-2">
          <BarChart3 size={20} />
          Аналитика
        </h1>
        <div className="tabs-pill">
          {periods.map(p => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={period === p.value ? 'tab-active' : ''}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 animate-fade-in-delay-1">
        <KpiCard
          label="Выручка"
          value={kpis ? formatRub(kpis.revenue) : '—'}
          icon={<Wallet size={16} className="text-apple-blue" />}
          iconBg="bg-blue-50"
          cur={kpis?.revenue ?? 0}
          prev={kpis?.revenue_prev ?? 0}
        />
        <KpiCard
          label="Записей"
          value={kpis ? String(kpis.bookings) : '—'}
          icon={<Calendar size={16} className="text-apple-success" />}
          iconBg="bg-green-50"
          cur={kpis?.bookings ?? 0}
          prev={kpis?.bookings_prev ?? 0}
        />
        <KpiCard
          label="Средний чек"
          value={kpis ? formatRub(kpis.avg_check) : '—'}
          icon={<Receipt size={16} className="text-apple-warning" />}
          iconBg="bg-orange-50"
          cur={kpis?.avg_check ?? 0}
          prev={kpis?.avg_check_prev ?? 0}
        />
        <KpiCard
          label="Загрузка"
          value={
            kpis
              ? kpis.load_percent != null
                ? `${kpis.load_percent.toFixed(1)}%`
                : '—'
              : '—'
          }
          icon={<Activity size={16} className="text-apple-danger" />}
          iconBg="bg-red-50"
          cur={kpis?.load_percent ?? 0}
          prev={kpis?.load_percent_prev ?? 0}
          isPoints
        />
      </div>

      {/* Daily chart */}
      <div className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-4 animate-fade-in-delay-2">
        <h2 className="font-semibold text-apple-text mb-4 text-sm">Записи и выручка по дням</h2>
        <DailyChart daily={data?.daily ?? []} />
      </div>

      {/* Top services + top employees */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-fade-in-delay-2">
        <TopCard
          title="Топ услуг"
          icon={<Scissors size={14} className="text-apple-blue" />}
          items={data?.top_services ?? []}
        />
        <TopCard
          title="Топ сотрудников"
          icon={<User size={14} className="text-apple-blue" />}
          items={data?.top_employees ?? []}
        />
      </div>
    </div>
  )
}
