import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './context/AuthContext.jsx';
import { Shell } from './components/Shell.jsx';
import { AuthPage } from './pages/Auth.jsx';
import { Landing } from './pages/Landing.jsx';
import { Overview } from './pages/Overview.jsx';
import { Transactions } from './pages/Transactions.jsx';
import { Wallet } from './pages/Wallet.jsx';
import { Payments } from './pages/Payments.jsx';
import { FraudCases } from './pages/Fraud.jsx';
import { Notifications } from './pages/Notifications.jsx';
import { Onboarding } from './pages/Onboarding.jsx';
import { FeatureStatus } from './pages/FeatureStatus.jsx';

function Guard({ children }) {
  const { authenticated, booting, user } = useAuth();
  const location = useLocation();
  if (booting) return <div className="boot-screen"><span className="spinner" /> Securing your session…</div>;
  if (authenticated && user?.onboarding_status && user.onboarding_status !== 'approved' && location.pathname !== '/onboarding') return <Navigate to="/onboarding" replace />;
  return authenticated ? children : <Navigate to="/login" replace />;
}

function OnboardingGuard({ children }) {
  const { authenticated, booting, user } = useAuth();
  if (booting) return <div className="boot-screen"><span className="spinner" /> Securing your session…</div>;
  if (!authenticated) return <Navigate to="/auth?mode=login" replace />;
  if (user?.onboarding_status === 'approved') return <Navigate to="/overview" replace />;
  return children;
}

export default function App() {
  const { authenticated } = useAuth();
  return <Routes>
    <Route path="/" element={<Landing />} />
    <Route path="/auth" element={authenticated ? <Navigate to="/overview" replace /> : <AuthPage />} />
    <Route path="/login" element={<Navigate to="/auth?mode=login" replace />} />
    <Route path="/register" element={<Navigate to="/auth?mode=register" replace />} />
    <Route path="/onboarding" element={<OnboardingGuard><Onboarding /></OnboardingGuard>} />
    <Route element={<Guard><Shell /></Guard>}>
      <Route path="overview" element={<Overview />} />
      <Route path="transactions" element={<Transactions />} />
      <Route path="wallet" element={<Wallet />} />
      <Route path="payments" element={<Payments />} />
      <Route path="notifications" element={<Notifications />} />
      <Route path="fraud" element={<FraudCases />} />
      <Route path="insights" element={<FeatureStatus feature="insights" />} />
      <Route path="savings" element={<FeatureStatus feature="savings" />} />
      <Route path="assistant" element={<FeatureStatus feature="assistant" />} />
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Route>
  </Routes>;
}
