import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { ThemeProvider } from "@/components/theme-provider";
import { AuthProvider, useAuth } from "@/lib/auth-context";
import { hasAdminAccess } from "@/lib/roles";
import Login from "@/pages/Login";
import Chat from "@/pages/Chat";
import AdminPage from "@/pages/AdminPage";
import SettingsPage from "@/pages/SettingsPage";

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return children;
};

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!hasAdminAccess(user?.role)) {
    return <Navigate to="/" replace />;
  }
  return children;
}

function DocumentTitleSync() {
  const location = useLocation();
  const titles: Record<string, string> = {
    "/": "Chat — RootAgent",
    "/login": "Sign in — RootAgent",
    "/admin": "Admin — RootAgent",
    "/settings": "Settings — RootAgent",
  };
  useDocumentTitle(titles[location.pathname] ?? "RootAgent");
  return null;
}

export default function App() {
  return (
    <ThemeProvider defaultTheme="dark" storageKey="rootagent-theme">
    <AuthProvider>
      <BrowserRouter>
        <DocumentTitleSync />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Chat />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <ProtectedRoute>
                <AdminRoute>
                  <AdminPage />
                </AdminRoute>
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <SettingsPage />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
    </ThemeProvider>
  );
}
