import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/shell/AppShell";
import { ProtectedRoute } from "./components/shell/ProtectedRoute";
import { ArchivePage } from "./pages/ArchivePage";
import { DocumentPage } from "./pages/DocumentPage";
import { LoginPage } from "./pages/LoginPage";
import { SessionProvider } from "./state/SessionContext";

export function App() {
  return (
    <SessionProvider>
      <Routes>
        <Route path="/dang-nhap" element={<LoginPage />} />
        <Route
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route path="/van-ban" element={<ArchivePage />} />
          <Route path="/van-ban/:documentId" element={<DocumentPage />} />
        </Route>
        <Route path="/" element={<Navigate to="/van-ban" replace />} />
        <Route path="*" element={<Navigate to="/van-ban" replace />} />
      </Routes>
    </SessionProvider>
  );
}
