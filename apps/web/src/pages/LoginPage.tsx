import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate } from "react-router-dom";

import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { useSession } from "../state/SessionContext";

/**
 * IA-00 — Enter the product / login shell
 * (`docs/design/01_INFORMATION_ARCHITECTURE.md`).
 *
 * The supplied API/data contracts do not define an authentication endpoint, so this
 * is a screen/state handoff only: submitting confirms server connectivity and enters
 * the shell. No account creation, password reset, or role management is implemented.
 */
export function LoginPage() {
  const { user, login, isSubmitting, error, clearError } = useSession();
  const [name, setName] = useState("");

  if (user) {
    return <Navigate to="/van-ban" replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await login(name.trim());
    } catch {
      // Error state is already reflected via session context.
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-mg-canvas px-4">
      <div className="w-full max-w-sm rounded-mg-lg border border-mg-border bg-mg-surface p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-mg-accent">MamaGift</p>
        <h1 className="mt-2 text-2xl font-semibold text-mg-text">Đăng nhập</h1>
        <p className="mt-1 text-sm text-mg-text-muted">
          Trợ lý tài liệu gia đình. Đăng nhập để xem văn bản của bạn.
        </p>

        <form className="mt-6 flex flex-col gap-4" onSubmit={handleSubmit} noValidate>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="login-name" className="text-sm font-medium text-mg-text">
              Tên của bạn
            </label>
            <Input
              id="login-name"
              name="name"
              autoComplete="name"
              placeholder="Ví dụ: Mẹ Lan"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                if (error) clearError();
              }}
              disabled={isSubmitting}
              required
            />
          </div>

          {error ? (
            <p role="alert" className="text-sm text-mg-danger">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={isSubmitting || !name.trim()} className="w-full">
            {isSubmitting ? "Đang đăng nhập…" : "Đăng nhập"}
          </Button>
        </form>
      </div>
    </main>
  );
}
