export interface CalendarBooking {
  businessName: string
  serviceName: string
  date: string
  time: string
  durationMinutes?: number | null
  address?: string | null
  description?: string | null
}

const DEFAULT_TIMEZONE = 'Europe/Moscow'

function pad(value: number) {
  return String(value).padStart(2, '0')
}

function icsDate(date: Date) {
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    'T',
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
  ].join('')
}

function escapeIcs(value: string) {
  return value
    .replace(/\\/g, '\\\\')
    .replace(/\r?\n/g, '\\n')
    .replace(/,/g, '\\,')
    .replace(/;/g, '\\;')
}

export function downloadBookingIcs(booking: CalendarBooking) {
  const [year, month, day] = booking.date.split('-').map(Number)
  const [hours, minutes] = booking.time.split(':').map(Number)
  const start = new Date(year, month - 1, day, hours, minutes, 0)
  const end = new Date(start.getTime() + Math.max(booking.durationMinutes || 60, 15) * 60_000)

  const uid = `servgo-${booking.date}-${booking.time.replace(':', '')}-${Date.now()}@servgo`
  const title = `${booking.businessName} — ${booking.serviceName}`
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//ServGo//Booking Calendar//RU',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:${uid}`,
    `DTSTAMP:${icsDate(new Date())}Z`,
    `DTSTART;TZID=${DEFAULT_TIMEZONE}:${icsDate(start)}`,
    `DTEND;TZID=${DEFAULT_TIMEZONE}:${icsDate(end)}`,
    `SUMMARY:${escapeIcs(title)}`,
    booking.address ? `LOCATION:${escapeIcs(booking.address)}` : '',
    booking.description ? `DESCRIPTION:${escapeIcs(booking.description)}` : '',
    'BEGIN:VALARM',
    'TRIGGER:-P1D',
    'ACTION:DISPLAY',
    'DESCRIPTION:Напоминание о записи ServGo',
    'END:VALARM',
    'BEGIN:VALARM',
    'TRIGGER:-PT2H',
    'ACTION:DISPLAY',
    'DESCRIPTION:Через 2 часа ваша запись ServGo',
    'END:VALARM',
    'END:VEVENT',
    'END:VCALENDAR',
  ].filter(Boolean)

  const blob = new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `servgo-${booking.date}-${booking.time.replace(':', '-')}.ics`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
