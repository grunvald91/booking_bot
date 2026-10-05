// === Type definitions ===

export interface Business {
  id: number;
  name: string;
  description?: string;
  business_type?: string;
  address?: string;
  phone?: string;
  working_hours_start?: string;
  working_hours_end?: string;
  photos?: string;
  directions?: string;
  services_count?: number;
  // Legacy compatibility
  working_hours?: string;
  photo_url?: string;
  rating?: number;
  reviews_count?: number;
}

export interface GroupPricingTier {
  min_people: number;
  max_people: number;
  price: number;
}

export interface Service {
  id: number;
  name: string;
  description?: string;
  price?: number;
  duration_minutes?: number;
  is_active: boolean;
  is_additional?: boolean;
  is_hourly_price?: boolean;
  sort_order?: number;
  pricing_type?: string;  // 'fixed' | 'per_person'
  group_pricing?: GroupPricingTier[] | null;
  // Legacy compatibility
  duration?: number;
}

export interface Employee {
  id: number;
  name: string;
  role?: string;
  specialization?: string;
  description?: string;
  photo_url?: string;
  is_active?: boolean;
  telegram_id?: number;
  booking_interval_minutes?: number;
  capacity?: number;
  area_sqm?: number;
  min_booking_minutes?: number;
  solo_price_per_hour?: number;
  photos?: string;
  primary_photo?: string;
  on_duty_date?: string;
  service_ids?: number[];
}

export interface TimePricing {
  time_from: string;
  time_to: string;
  price_per_hour: number;
  day_type: string;
}

export interface EmployeeWithPricing extends Employee {
  description?: string;
  capacity?: number;
  solo_price_per_hour?: number;
  time_pricing?: TimePricing[];
}

export interface PriceSegment {
  time_from: string;
  time_to: string;
  minutes: number;
  price_per_hour: number;
  subtotal: number;
}

export interface CalculatePriceResponse {
  has_time_price: boolean;
  total: number;
  segments: PriceSegment[];
}

export interface BusinessDetail extends Business {
  services: Service[];
  employees: EmployeeWithPricing[];
  break_start?: string;
  break_end?: string;
  business_type?: string;
  prepayment_enabled?: boolean;
  prepayment_percent?: number;
  payment_phone?: string;
  payment_details?: string;
  cancellation_policy_photo?: string;
  cancellation_policy_text?: string;
  require_receipt_for_prepayment?: boolean;
  booking_labels?: Record<string, string>;
  booking_flow_order?: 'service_first' | 'resource_first';
}

export interface Booking {
  id: number;
  business_id: number;
  service_id: number;
  business_name: string;
  service_name: string;
  service_price?: number;
  employee_name?: string;
  date: string;
  time: string;
  duration?: number;
  price?: number;
  status: string;
  notes?: string;
  created_at: string;
  can_cancel?: boolean;
  can_reschedule?: boolean;
}

export interface SubscriptionServiceItem {
  id: number;
  name: string;
  quantity: number;
}

export interface SubscriptionPlan {
  id: number;
  name: string;
  description?: string;
  price: number;
  sessions_count?: number;
  validity_days: number;
  services: SubscriptionServiceItem[];
}

export interface ClientSubscription {
  id: number;
  subscription_name: string;
  business_name: string;
  status: string;
  sessions_remaining: number;
  sessions_total: number;
  valid_until?: string;
  payment_status?: string;
  created_at: string;
}

export interface CreateBookingData {
  business_id: number;
  service_ids: number[];
  additional_service_ids?: number[];
  additional_service_hours?: Record<string, number>;
  is_solo_booking?: boolean;
  employee_id?: number;
  date: string;
  time: string;
  client_name: string;
  client_phone: string;
  notes?: string;
  repeat_weeks?: number;
}

export interface AdminBooking {
  id: number;
  client_name: string;
  client_phone?: string;
  service_name: string;
  service_duration?: number;
  price?: number;
  is_rental?: boolean;
  price_requires_confirmation?: boolean;
  prepayment_amount?: number | null;
  employee_name?: string;
  employee_id?: number;
  date: string;
  time: string;
  status: string;
  notes?: string;
  created_at?: string;
}

export interface ManualBookingData {
  business_id: number;
  service_id: number;
  employee_id?: number;
  date: string;
  time: string;
  client_name: string;
  client_phone?: string;
  notes?: string;
  repeat_weeks?: number;
}

export interface DashboardData {
  today_bookings: number;
  total_revenue: number;
  pending_count: number;
  confirmed_count: number;
}

export interface AnalyticsData {
  revenue: number;
  bookings_count: number;
  avg_check: number;
  top_services: { name: string; count: number }[];
  revenue_by_day: { date: string; revenue: number }[];
}

export interface AnalyticsTopItem {
  id: number;
  name: string;
  count: number;
  revenue: number;
  share_percent: number;
}

export interface AnalyticsDailyPoint {
  date: string;
  bookings: number;
  revenue: number;
}

export interface AnalyticsOverview {
  kpis: {
    revenue: number;
    bookings: number;
    avg_check: number;
    load_percent: number | null;
    revenue_prev: number;
    bookings_prev: number;
    avg_check_prev: number;
    load_percent_prev: number | null;
  };
  top_services: AnalyticsTopItem[];
  top_employees: AnalyticsTopItem[];
  daily: AnalyticsDailyPoint[];
}

export interface BusinessAdminDetail {
  id: number;
  name: string;
  description?: string;
  business_type: string;
  address?: string;
  phone?: string;
  working_hours_start?: string;
  working_hours_end?: string;
  break_start?: string;
  break_end?: string;
  booking_interval_minutes?: number;
  directions?: string;
  photos?: string;
  video?: string;
  prepayment_enabled: boolean;
  prepayment_percent?: number;
  payment_phone?: string;
  payment_details?: string;
  cancellation_policy_photo?: string;
  cancellation_policy_text?: string;
  require_receipt_for_prepayment: boolean;
  booking_labels?: Record<string, string>;
  booking_flow_order?: 'service_first' | 'resource_first';
}

export interface BusinessUpdateData {
  name?: string;
  description?: string;
  address?: string;
  phone?: string;
  working_hours_start?: string;
  working_hours_end?: string;
  break_start?: string;
  break_end?: string;
  directions?: string;
  booking_interval_minutes?: number;
  prepayment_enabled?: boolean;
  prepayment_percent?: number;
  payment_phone?: string;
  payment_details?: string;
  cancellation_policy_text?: string;
  require_receipt_for_prepayment?: boolean;
  booking_labels?: Record<string, string>;
  booking_flow_order?: 'service_first' | 'resource_first';
}

export interface OwnerInfo {
  id: number;
  user_id: number;
  role: string;
  user_name: string;
  user_phone?: string;
  telegram_id?: number;
  added_at?: string;
}

export interface TimePricingAdmin {
  id: number;
  time_from: string;
  time_to: string;
  price_per_hour: number;
  day_type: string;
}

export interface EmployeeServiceLink {
  service_id: number;
  service_name: string;
}

export interface SubscriptionAdmin {
  id: number;
  name: string;
  description?: string;
  price: number;
  validity_days: number;
  rules?: string;
  is_active: boolean;
  services: SubscriptionServiceItem[];
}

export interface SubscriptionCreateData {
  name: string;
  description?: string;
  price: number;
  validity_days: number;
  rules?: string;
  services: { service_id: number; quantity: number }[];
}

export interface AuthResponse {
  token: string;
  role: 'client' | 'admin' | 'owner';
  user: {
    id: number;
    full_name: string;
    phone?: string;
    username?: string;
  };
}

// === API Client ===

const API = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('token');
  const tgInitData = window.Telegram?.WebApp?.initData || '';
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(tgInitData ? { 'X-Telegram-Init-Data': tgInitData } : {}),
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Auth
  loginPhone: (phone: string) =>
    request<{ message: string; fallback?: boolean }>('/auth/phone', {
      method: 'POST',
      body: JSON.stringify({ phone }),
    }),
  verifyCode: (phone: string, code: string) =>
    request<AuthResponse>('/auth/verify', {
      method: 'POST',
      body: JSON.stringify({ phone, code }),
    }),
  telegramAuth: (initData: string) =>
    request<AuthResponse>('/auth/telegram', {
      method: 'POST',
      body: JSON.stringify({ init_data: initData }),
    }),
  getMe: () => request<AuthResponse['user']>('/auth/me'),

  // Client
  getBusinesses: () => request<Business[]>('/businesses'),
  getBusiness: (id: number) => request<BusinessDetail>(`/businesses/${id}`),
  getSlots: async (bizId: number, serviceId: number, date: string, employeeId?: number) => {
    const employeeQuery = employeeId ? `&employee_id=${employeeId}` : '';
    const data = await request<Array<{ time: string } | string>>(
      `/businesses/${bizId}/slots?service_id=${serviceId}&date=${date}${employeeQuery}`
    );
    // Normalize: API returns [{time:"09:00"},...] but we need ["09:00",...]
    return data.map((s) => (typeof s === 'string' ? s : s.time));
  },
  calculatePrice: (
    bizId: number,
    employeeId: number,
    time: string,
    duration: number,
    date?: string
  ) =>
    request<CalculatePriceResponse>(
      `/businesses/${bizId}/calculate-price?employee_id=${employeeId}&time=${time}&duration=${duration}${date ? '&date=' + date : ''}`
    ),
  createBooking: (data: CreateBookingData) =>
    request<Booking>('/bookings', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  rescheduleBooking: (id: number, date: string, time: string) =>
    request<{ success: boolean; message: string }>(`/bookings/${id}/reschedule`, {
      method: 'POST',
      body: JSON.stringify({ date, time }),
    }),
  getMyBookings: () => request<Booking[]>('/my/bookings'),
  cancelBooking: (id: number) =>
    request<{ message: string }>(`/bookings/${id}/cancel`, { method: 'POST' }),
  prepaymentSent: (bookingId: number) =>
    request<{ message: string }>(`/bookings/${bookingId}/prepayment-sent`, { method: 'POST' }),
  uploadReceipt: async (bookingId: number, file: File): Promise<{ message: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const token = localStorage.getItem('token');
    const tgInitData = window.Telegram?.WebApp?.initData || '';
    const res = await fetch(`${API}/bookings/${bookingId}/receipt`, {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(tgInitData ? { 'X-Telegram-Init-Data': tgInitData } : {}),
      },
      body: formData,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return res.json();
  },
  // QR/guest flow (no auth): identify the booking by its notify-token.
  prepaymentSentByToken: (notifyToken: string) =>
    request<{ message: string }>(`/bookings/by-token/${notifyToken}/prepayment-sent`, { method: 'POST' }),
  uploadReceiptByToken: async (notifyToken: string, file: File): Promise<{ message: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API}/bookings/by-token/${notifyToken}/receipt`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return res.json();
  },

  // Subscriptions
  getSubscriptions: (businessId: number) =>
    request<SubscriptionPlan[]>(`/subscriptions?business_id=${businessId}`),
  getSubscriptionDetails: (id: number) =>
    request<SubscriptionPlan>(`/subscriptions/${id}`),
  buySubscription: (id: number) =>
    request<ClientSubscription>(`/subscriptions/${id}/buy`, { method: 'POST', body: JSON.stringify({}) }),
  getMySubscriptions: () =>
    request<ClientSubscription[]>('/my/subscriptions'),
  subscriptionPaymentSent: (clientSubId: number) =>
    request<{ message: string }>(`/my/subscriptions/${clientSubId}/payment-sent`, { method: 'POST' }),

  // Admin
  getDashboard: () => request<DashboardData>('/admin/dashboard'),
  getAdminBookings: (params?: string) =>
    request<AdminBooking[]>(`/admin/bookings${params ? '?' + params : ''}`),
  createManualBooking: (data: ManualBookingData) =>
    request<AdminBooking[]>('/admin/bookings', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateBookingStatus: (bookingId: number, status: string) =>
    request<AdminBooking>(`/admin/bookings/${bookingId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),
  updateRentalQuote: (bookingId: number, estimatedPrice: number, prepaymentAmount: number) =>
    request<AdminBooking>(`/admin/rental/bookings/${bookingId}/quote`, {
      method: 'PATCH',
      body: JSON.stringify({ estimated_price: estimatedPrice, prepayment_amount: prepaymentAmount }),
    }),
  adminReschedule: (bookingId: number, date: string, time: string, employeeId?: number) =>
    request<AdminBooking>(`/admin/bookings/${bookingId}/reschedule`, {
      method: 'POST',
      body: JSON.stringify({ date, time, employee_id: employeeId }),
    }),
  getServices: (bizId: number) =>
    request<Service[]>(`/admin/businesses/${bizId}/services`),
  updateService: (bizId: number, serviceId: number, data: Partial<Service>) =>
    request<Service>(`/admin/businesses/${bizId}/services/${serviceId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  createService: (bizId: number, data: Partial<Service>) =>
    request<Service>(`/admin/businesses/${bizId}/services`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  deleteService: (bizId: number, serviceId: number) =>
    request<void>(`/admin/businesses/${bizId}/services/${serviceId}`, {
      method: 'DELETE',
    }),
  getEmployees: (bizId: number, includeInactive: boolean = false) =>
    request<Employee[]>(
      `/admin/businesses/${bizId}/employees${includeInactive ? '?include_inactive=true' : ''}`
    ),
  createEmployee: (bizId: number, data: Partial<Employee>) =>
    request<Employee>(`/admin/businesses/${bizId}/employees`, { method: 'POST', body: JSON.stringify(data) }),
  updateEmployee: (bizId: number, empId: number, data: Partial<Employee>) =>
    request<Employee>(`/admin/businesses/${bizId}/employees/${empId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteEmployee: (bizId: number, empId: number) =>
    request<void>(`/admin/businesses/${bizId}/employees/${empId}`, { method: 'DELETE' }),
  getAnalytics: (bizId: number, period?: string) =>
    request<AnalyticsData>(
      `/admin/analytics/${bizId}${period ? '?period=' + period : ''}`
    ),
  getAnalyticsOverview: (bizId: number, days: number) =>
    request<AnalyticsOverview>(`/admin/analytics/${bizId}/overview?days=${days}`),
  getAdminBusinesses: () =>
    request<Business[]>('/admin/businesses'),
  getBusinessDetail: (bizId: number) =>
    request<BusinessAdminDetail>(`/admin/businesses/${bizId}/detail`),
  updateBusiness: (bizId: number, data: BusinessUpdateData) =>
    request<BusinessAdminDetail>(`/admin/businesses/${bizId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Service reorder
  reorderServices: (bizId: number, serviceIds: number[]) =>
    request<{ message: string }>(`/admin/businesses/${bizId}/services/reorder`, {
      method: 'POST',
      body: JSON.stringify({ service_ids: serviceIds }),
    }),

  // Employee-Service links
  getEmployeeServices: (bizId: number, empId: number) =>
    request<EmployeeServiceLink[]>(`/admin/businesses/${bizId}/employees/${empId}/services`),
  setEmployeeServices: (bizId: number, empId: number, serviceIds: number[]) =>
    request<{ message: string }>(`/admin/businesses/${bizId}/employees/${empId}/services`, {
      method: 'PUT',
      body: JSON.stringify({ service_ids: serviceIds }),
    }),

  // Venue time pricing
  getTimePricing: (bizId: number, empId: number) =>
    request<TimePricingAdmin[]>(`/admin/businesses/${bizId}/employees/${empId}/time-pricing`),
  addTimePricing: (bizId: number, empId: number, data: { time_from: string; time_to: string; price_per_hour: number; day_type?: string }) =>
    request<TimePricingAdmin>(`/admin/businesses/${bizId}/employees/${empId}/time-pricing`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  deleteTimePricing: (bizId: number, empId: number, pricingId: number) =>
    request<{ message: string }>(`/admin/businesses/${bizId}/employees/${empId}/time-pricing/${pricingId}`, {
      method: 'DELETE',
    }),

  // Duty toggle
  toggleDuty: (bizId: number, empId: number) =>
    request<{ on_duty: boolean; date: string }>(`/admin/businesses/${bizId}/employees/${empId}/toggle-duty`, {
      method: 'POST',
    }),

  // Co-owners
  getOwners: (bizId: number) =>
    request<OwnerInfo[]>(`/admin/businesses/${bizId}/owners`),
  addOwner: (bizId: number, data: { telegram_id?: number; username?: string }) =>
    request<OwnerInfo>(`/admin/businesses/${bizId}/owners`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  removeOwner: (bizId: number, ownerId: number) =>
    request<{ message: string }>(`/admin/businesses/${bizId}/owners/${ownerId}`, {
      method: 'DELETE',
    }),

  // Subscriptions admin
  getAdminSubscriptions: (bizId: number) =>
    request<SubscriptionAdmin[]>(`/admin/businesses/${bizId}/subscriptions`),
  createSubscription: (bizId: number, data: SubscriptionCreateData) =>
    request<SubscriptionAdmin>(`/admin/businesses/${bizId}/subscriptions`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateSubscription: (bizId: number, subId: number, data: Partial<SubscriptionCreateData> & { is_active?: boolean }) =>
    request<SubscriptionAdmin>(`/admin/businesses/${bizId}/subscriptions/${subId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteSubscription: (bizId: number, subId: number) =>
    request<{ message: string }>(`/admin/businesses/${bizId}/subscriptions/${subId}`, {
      method: 'DELETE',
    }),

  // Duty schedule
  getDutySchedule: (bizId: number, empId: number) =>
    request<{ dates: string[] }>(`/admin/businesses/${bizId}/employees/${empId}/duty-schedule`),
  setDutySchedule: (bizId: number, empId: number, dates: string[]) =>
    request<{ dates: string[] }>(`/admin/businesses/${bizId}/employees/${empId}/duty-schedule`, {
      method: 'PUT',
      body: JSON.stringify({ dates }),
    }),

  // QR code
  getQrUrl: (bizId: number, target: 'webapp' | 'telegram') =>
    `/api/admin/businesses/${bizId}/qr?target=${target}`,

  // Business photo management
  uploadBusinessPhoto: async (bizId: number, file: File): Promise<{ file_id: string; photos: string[] }> => {
    const formData = new FormData();
    formData.append('file', file);
    const token = localStorage.getItem('token');
    const tgInitData = window.Telegram?.WebApp?.initData || '';
    const res = await fetch(`${API}/admin/businesses/${bizId}/photo`, {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(tgInitData ? { 'X-Telegram-Init-Data': tgInitData } : {}),
      },
      body: formData,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return res.json();
  },
  deleteBusinessPhoto: (bizId: number, photoIndex: number) =>
    request<{ photos: string[] }>(`/admin/businesses/${bizId}/photo/${photoIndex}`, { method: 'DELETE' }),

  // Employee photo management
  uploadEmployeePhoto: async (bizId: number, empId: number, file: File): Promise<{ file_id: string; photos: string[]; primary_photo?: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const token = localStorage.getItem('token');
    const tgInitData = window.Telegram?.WebApp?.initData || '';
    const res = await fetch(`${API}/admin/businesses/${bizId}/employees/${empId}/photo`, {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(tgInitData ? { 'X-Telegram-Init-Data': tgInitData } : {}),
      },
      body: formData,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return res.json();
  },
  deleteEmployeePhoto: (bizId: number, empId: number, photoIndex: number) =>
    request<{ photos: string[]; primary_photo?: string }>(`/admin/businesses/${bizId}/employees/${empId}/photo/${photoIndex}`, { method: 'DELETE' }),
  setEmployeePrimaryPhoto: (bizId: number, empId: number, fileId: string) =>
    request<{ photos: string[]; primary_photo: string }>(`/admin/businesses/${bizId}/employees/${empId}/primary-photo`, {
      method: 'PUT',
      body: JSON.stringify({ file_id: fileId }),
    }),

  // AI Chat
  aiChat: (message: string, businessId?: number) =>
    request<{ reply: string; pending_action?: { action_id: string; description: string; tool_name: string } }>('/ai/chat', {
      method: 'POST',
      body: JSON.stringify({ message, business_id: businessId }),
    }),
  aiConfirm: (actionId: string) =>
    request<{ reply: string }>('/ai/confirm', {
      method: 'POST',
      body: JSON.stringify({ action_id: actionId }),
    }),
  aiReject: (actionId: string) =>
    request<{ message: string }>('/ai/reject', {
      method: 'POST',
      body: JSON.stringify({ action_id: actionId }),
    }),
};
