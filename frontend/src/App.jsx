import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './context/AuthContext.jsx';
import { Shell } from './components/Shell.jsx';
import { Login, Register } from './pages/Auth.jsx';
import { Overview } from './pages/Overview.jsx';
import { Transactions } from './pages/Transactions.jsx';
import { Wallet } from './pages/Wallet.jsx';
import { Payments } from './pages/Payments.jsx';
import { FraudCases } from './pages/Fraud.jsx';
import { Notifications } from './pages/Notifications.jsx';

function Guard({ children }) {
  const { authenticated, booting } = useAuth();
  if (booting) return <div className="boot-screen"><span className="spinner" /> Securing your session…</div>;
  return authenticated ? children : <Navigate to="/login" replace />;
}

export default function App() {
  const { authenticated } = useAuth();
  return <Routes>
    <Route path="/login" element={authenticated ? <Navigate to="/" replace /> : <Login />} />
    <Route path="/register" element={authenticated ? <Navigate to="/" replace /> : <Register />} />
    <Route element={<Guard><Shell /></Guard>}>
      <Route index element={<Overview />} />
      <Route path="transactions" element={<Transactions />} />
      <Route path="wallet" element={<Wallet />} />
      <Route path="payments" element={<Payments />} />
      <Route path="notifications" element={<Notifications />} />
      <Route path="fraud" element={<FraudCases />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Route>
  </Routes>;
}
