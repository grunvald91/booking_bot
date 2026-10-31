import type { BusinessDetail, EmployeeWithPricing, Service } from '../../api/client'

// Если услугу явно выполняет хотя бы один специалист, доступны только специалисты
// с этой привязкой. В остальных случаях сохраняем историческую семантику service_ids.
export function resourceSupportsService(
  resource: EmployeeWithPricing | null | undefined,
  serviceId: number,
  all: EmployeeWithPricing[],
): boolean {
  if (!resource) return true
  const explicit = all.some((r) => (r.service_ids || []).includes(serviceId))
  if (explicit) return (resource.service_ids || []).includes(serviceId)
  return (resource.service_ids || []).length === 0
}

export type BookingEntryStep = 'home' | 'services' | 'resource' | 'calendar'

export function resolveBookingEntry(
  business: BusinessDetail,
  serviceId: number | null,
  employeeId: number | null,
): { services: Service[]; resource: EmployeeWithPricing | null; step: BookingEntryStep } {
  const allServices = business.services.filter((service) => service.is_active && !service.is_additional)
  const employees = business.employees || []
  const hasSelection = serviceId !== null || employeeId !== null

  let service = allServices.find((item) => item.id === serviceId)
  let resource = employees.find((item) => item.id === employeeId) || null

  // Противоречивые параметры нельзя превращать в недоступную комбинацию.
  // Приоритет у явно выбранной услуги, а специалиста клиент сможет выбрать заново.
  if (service && resource && !resourceSupportsService(resource, service.id, employees)) {
    resource = null
  }

  // Если специалист оказывает только одну доступную услугу, повторный выбор не нужен.
  if (!service && resource) {
    const suitable = allServices.filter((item) => resourceSupportsService(resource, item.id, employees))
    if (suitable.length === 1) service = suitable[0]
  }

  // Если услугу оказывает только один специалист, не заставляем выбирать его повторно.
  // Для аренды зал остаётся явным выбором, даже если доступен лишь один.
  if (service && !resource && business.business_type !== 'venue_rental') {
    const suitable = employees.filter((item) => resourceSupportsService(item, service.id, employees))
    if (suitable.length === 1) resource = suitable[0]
  }

  const step: BookingEntryStep = !hasSelection
    ? 'home'
    : !service
      ? 'services'
      : employees.length > 0 && !resource
        ? 'resource'
        : 'calendar'

  return { services: service ? [service] : [], resource, step }
}
