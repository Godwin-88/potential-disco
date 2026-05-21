import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import ProtectedRoute from './auth/ProtectedRoute'
import { ToastProvider } from './components/Toast'
import Landing   from './pages/Landing'
import Login     from './pages/Login'
import Signup    from './pages/Signup'
import Shell     from './pages/app/Shell'
import QA        from './pages/app/QA'
import Compliance from './pages/app/Compliance'
import Predictor from './pages/app/Predictor'
import Graph     from './pages/app/Graph'

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Routes>
          {/* Public */}
          <Route path="/"       element={<Landing />} />
          <Route path="/login"  element={<Login />} />
          <Route path="/signup" element={<Signup />} />

          {/* Protected */}
          <Route element={<ProtectedRoute />}>
            <Route path="/app" element={<Shell />}>
              <Route index element={<Navigate to="/app/qa" replace />} />
              <Route path="qa"         element={<QA />} />
              <Route path="compliance" element={<Compliance />} />
              <Route path="predictor"  element={<Predictor />} />
              <Route path="graph"      element={<Graph />} />
            </Route>
          </Route>

          {/* Catch-all */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ToastProvider>
    </AuthProvider>
  )
}
