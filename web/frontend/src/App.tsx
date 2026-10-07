import { useState, useEffect } from 'react'
import { Routes, Route, Navigate, useSearchParams } from 'react-router-dom'
import { api } from './api/client'
import { Layout } from './components/Layout'
import { HomePage } from './pages/client/HomePage'
import { BusinessPage } from './pages/client/BusinessPage'
import { BookingPage } from './pages/client/BookingPage'
import { BookingStatusPage } from './pages/client/BookingStatusPage'
import { MyBookingsPage } from './pages/client/MyBookingsPage'
import { SubscriptionsPage } from './pages/client/SubscriptionsPage'
import { LoginPage } from './pages/client/LoginPage'
import { AccountPage } from './pages/client/AccountPage'
import { PrepaymentsPage } from './pages/admin/PrepaymentsPage'
import { AdminPaymentAttention } from './components/AdminPaymentAttention'
import { AdminDashboard } from './pages/admin/AdminDashboard'
import { SchedulePage } from './pages/admin/SchedulePage'
import { ServicesPage } from './pages/admin/ServicesPage'
import { EmployeesPage } from './pages/admin/EmployeesPage'
import { AnalyticsPage } from './pages/admin/AnalyticsPage'
import { SettingsPage } from './pages/admin/SettingsPage'
import { SubscriptionsAdminPage } from './pages/admin/SubscriptionsAdminPage'
import { ChatPage } from './pages/client/ChatPage'
import { SalesInboxPage } from './pages/admin/SalesInboxPage'
import { SalesSettingsPage } from './pages/admin/SalesSettingsPage'
import { RentalBookingStatusPage } from './pages/client/RentalBookingStatusPage'
import { LegalPage } from './pages/client/LegalPage'

/** Redirect /book?business_id=X → /book/X, or /book → / */
function BookRedirect() {
  const [params] = useSearchParams()
  const bizId = params.get('business_id')
  if (bizId) return <Navigate to={`/book/${bizId}`} replace />
  return <Navigate to="/" replace />
}

/** Redirect /schedule, /analytics, /calendar → admin routes */
function LegacyAdminRedirect({ to }: { to: string }) {
  return <Navigate to={to} replace />
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token')
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token')
  const role = localStorage.getItem('userRole')
  if (!token || (role !== 'admin' && role !== 'owner')) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

function App() {
  const [tgAuthDone, setTgAuthDone] = useState(() =>
    !window.Telegram?.WebApp?.initData || sessionStorage.getItem('servgoExplicitLogout') === '1')

  useEffect(() => {
    const initData = window.Telegram?.WebApp?.initData
    const explicitLogout = sessionStorage.getItem('servgoExplicitLogout') === '1'

    if (initData && !explicitLogout) {
      // Always refresh role from server — owner status may have changed,
      // and stale userRole='client' in localStorage hides admin UI.
      api.telegramAuth(initData)
        .then((res) => {
          localStorage.setItem('token', res.token)
          localStorage.setItem('userRole', res.role || 'client')
          localStorage.setItem('userName', res.user.full_name || 'Пользователь')
          setTgAuthDone(true)
        })
        .catch((err) => {
          console.warn('Telegram auto-login failed:', err)
          setTgAuthDone(true)
        })
    }
  }, [])

  if (!tgAuthDone) {
    return null // Wait for Telegram auth to complete before rendering routes
  }

  return (
    <><AdminPaymentAttention /><Routes>
      <Route element={<Layout />}>
        {/* Client routes */}
        <Route path="/" element={<HomePage />} />
        <Route path="/business/:id" element={<BusinessPage />} />
        <Route path="/book/:businessId" element={<BookingPage />} />
        <Route path="/b/:token" element={<BookingStatusPage />} />
        <Route path="/rental/b/:token" element={<RentalBookingStatusPage />} />
        <Route
          path="/my"
          element={
            <ProtectedRoute>
              <MyBookingsPage />
            </ProtectedRoute>
          }
        />
        <Route path="/subscriptions" element={<SubscriptionsPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/legal/:docType/:businessId" element={<LegalPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/account" element={<ProtectedRoute><AccountPage /></ProtectedRoute>} />
        <Route path="/admin/prepayments" element={<AdminRoute><PrepaymentsPage /></AdminRoute>} />

        {/* Legacy redirects */}
        <Route path="/book" element={<BookRedirect />} />
        <Route path="/schedule" element={<LegacyAdminRedirect to="/admin/schedule" />} />
        <Route path="/analytics" element={<LegacyAdminRedirect to="/admin/analytics" />} />
        <Route path="/calendar" element={<LegacyAdminRedirect to="/admin/schedule" />} />

        {/* Admin routes */}
        <Route path="/admin/sales" element={<AdminRoute><SalesInboxPage /></AdminRoute>} />
        <Route path="/admin/sales/settings" element={<AdminRoute><SalesSettingsPage /></AdminRoute>} />
        <Route
          path="/admin"
          element={
            <AdminRoute>
              <AdminDashboard />
            </AdminRoute>
          }
        />
        <Route
          path="/admin/schedule"
          element={
            <AdminRoute>
              <SchedulePage />
            </AdminRoute>
          }
        />
        <Route
          path="/admin/services"
          element={
            <AdminRoute>
              <ServicesPage />
            </AdminRoute>
          }
        />
        <Route
          path="/admin/employees"
          element={
            <AdminRoute>
              <EmployeesPage />
            </AdminRoute>
          }
        />
        <Route
          path="/admin/analytics"
          element={
            <AdminRoute>
              <AnalyticsPage />
            </AdminRoute>
          }
        />
        <Route
          path="/admin/settings"
          element={
            <AdminRoute>
              <SettingsPage />
            </AdminRoute>
          }
        />
        <Route
          path="/admin/subscriptions"
          element={
            <AdminRoute>
              <SubscriptionsAdminPage />
            </AdminRoute>
          }
        />
      </Route>
    </Routes></>
  )
}

export default App
