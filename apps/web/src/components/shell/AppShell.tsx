import * as RadixDialog from "@radix-ui/react-dialog";
import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import { LogOut, Menu, X } from "lucide-react";
import { useState } from "react";
import { Outlet } from "react-router-dom";

import { useSession } from "../../state/SessionContext";
import { Sidebar } from "./Sidebar";

/**
 * Desktop shell keeps the rail always visible; tablet/mobile open it as a drawer
 * (`docs/design/04_RESPONSIVE_STATES.md` sections 3.2, 3.3).
 */
export function AppShell() {
  const { user, logout } = useSession();
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="flex h-screen flex-col desktop:flex-row">
      <aside className="hidden w-64 shrink-0 border-r border-mg-border bg-mg-surface desktop:block">
        <Sidebar />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-mg-border bg-mg-surface px-3 desktop:px-6">
          <div className="flex items-center gap-2 desktop:hidden">
            <RadixDialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
              <RadixDialog.Trigger asChild>
                <button
                  type="button"
                  aria-label="Mở menu"
                  className="flex h-11 w-11 items-center justify-center rounded-mg-sm text-mg-text hover:bg-mg-surface-2"
                >
                  <Menu aria-hidden="true" size={20} />
                </button>
              </RadixDialog.Trigger>
              <RadixDialog.Portal>
                <RadixDialog.Overlay className="fixed inset-0 z-40 bg-mg-text/30" />
                <RadixDialog.Content className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-mg-surface shadow-xl focus:outline-none">
                  <VisuallyHidden.Root asChild>
                    <RadixDialog.Title>Menu</RadixDialog.Title>
                  </VisuallyHidden.Root>
                  <div className="flex justify-end p-2">
                    <RadixDialog.Close
                      aria-label="Đóng menu"
                      className="flex h-11 w-11 items-center justify-center rounded-mg-sm text-mg-text-muted hover:bg-mg-surface-2"
                    >
                      <X aria-hidden="true" size={20} />
                    </RadixDialog.Close>
                  </div>
                  <Sidebar onNavigate={() => setDrawerOpen(false)} />
                </RadixDialog.Content>
              </RadixDialog.Portal>
            </RadixDialog.Root>
            <span className="text-base font-semibold text-mg-text">MamaGift</span>
          </div>

          {user ? (
            <div className="ml-auto flex items-center gap-2">
              <span className="text-sm text-mg-text-muted">{user.name}</span>
              <button
                type="button"
                onClick={logout}
                aria-label="Đăng xuất"
                className="flex h-11 w-11 items-center justify-center rounded-mg-sm text-mg-text-muted hover:bg-mg-surface-2"
              >
                <LogOut aria-hidden="true" size={18} />
              </button>
            </div>
          ) : null}
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
