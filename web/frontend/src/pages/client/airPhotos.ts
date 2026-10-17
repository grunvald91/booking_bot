// Фото бизнесов и ресурсов: file_id из Telegram или готовые URL.

export function photoSrc(photo: string): string {
  if (/^https?:\/\//i.test(photo) || photo.startsWith('/')) return photo
  return `/api/telegram-photo/${encodeURIComponent(photo)}`
}

export function parsePhotoList(raw?: string | null): string[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.filter((v): v is string => typeof v === 'string' && v.length > 0)
  } catch {
    // одиночный file_id строкой
    return [raw]
  }
  return []
}
