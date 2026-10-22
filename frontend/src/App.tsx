import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { isLoggedIn } from './api/client';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Enroll from './pages/Enroll';
import Packages from './pages/Packages';
import PackageBuilder from './pages/PackageBuilder';
import Deployments from './pages/Deployments';
import AuditLog from './pages/AuditLog';
import RobotDetail from './pages/RobotDetail';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isLoggedIn()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Dashboard />} />
          <Route path="enroll" element={<Enroll />} />
          <Route path="robot/:serial" element={<RobotDetail />} />
          <Route path="packages" element={<Packages />} />
          <Route path="packages/new" element={<PackageBuilder />} />
          <Route path="deployments" element={<Deployments />} />
          <Route path="audit" element={<AuditLog />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
