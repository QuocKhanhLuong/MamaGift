import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { checkHealth } from "../api/health";
import { ApiRequestError } from "../api/client";

const STORAGE_KEY = "mamagift.session";

export interface SessionUser {
  name: string;
}

interface SessionState {
  user: SessionUser | null;
  isSubmitting: boolean;
  error: string | null;
  login: (name: string) => Promise<void>;
  logout: () => void;
  clearError: () => void;
}

const SessionContext = createContext<SessionState | null>(null);

function readStoredUser(): SessionUser | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SessionUser;
    return parsed.name ? parsed : null;
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(() => readStoredUser());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const login = useCallback(async (name: string) => {
    setIsSubmitting(true);
    setError(null);
    try {
      // No authentication contract exists yet (docs/design/01_INFORMATION_ARCHITECTURE.md IA-00):
      // this is a screen/state handoff, gated only on real server evidence of connectivity.
      await checkHealth();
      const nextUser: SessionUser = { name };
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextUser));
      setUser(nextUser);
    } catch (cause) {
      const message =
        cause instanceof ApiRequestError && cause.offline
          ? "Không thể kết nối máy chủ. Kiểm tra kết nối mạng và thử lại."
          : "Không thể đăng nhập.";
      setError(message);
      throw cause;
    } finally {
      setIsSubmitting(false);
    }
  }, []);

  const logout = useCallback(() => {
    window.localStorage.removeItem(STORAGE_KEY);
    setUser(null);
  }, []);

  const clearError = useCallback(() => setError(null), []);

  const value = useMemo(
    () => ({ user, isSubmitting, error, login, logout, clearError }),
    [user, isSubmitting, error, login, logout, clearError],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return context;
}
