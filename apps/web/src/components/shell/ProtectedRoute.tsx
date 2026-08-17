import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useSession } from "../../state/SessionContext";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user } = useSession();
  if (!user) {
    return <Navigate to="/dang-nhap" replace />;
  }
  return <>{children}</>;
}
