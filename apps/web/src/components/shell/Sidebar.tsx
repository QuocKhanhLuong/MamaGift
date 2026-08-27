import { FileText, Sparkles } from "lucide-react";
import { NavLink } from "react-router-dom";

import { cn } from "../../lib/cn";

/**
 * `docs/10_DESIGN_SYSTEM.md` section 6, `docs/design/01_INFORMATION_ARCHITECTURE.md` section 3.
 * Primary navigation destinations: `Văn bản` (/van-ban) and `Trợ lý` (/tro-ly) enabled in Phase 5.
 */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Điều hướng chính" className="flex h-full flex-col gap-6 p-4">
      <p className="px-2 text-lg font-semibold text-mg-text">MamaGift</p>
      <ul className="flex flex-col gap-1">
        <li>
          <NavLink
            to="/van-ban"
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex min-h-[44px] items-center gap-2 rounded-mg-sm px-2 text-[15px] font-medium text-mg-text",
                isActive ? "bg-mg-accent-soft text-mg-accent" : "hover:bg-mg-surface-2",
              )
            }
          >
            <FileText aria-hidden="true" size={18} />
            Văn bản
          </NavLink>
          <p className="mt-1 pl-8 text-sm text-mg-text-muted">Gần đây (bộ lọc)</p>
        </li>
        <li>
          <NavLink
            to="/tro-ly"
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex min-h-[44px] items-center gap-2 rounded-mg-sm px-2 text-[15px] font-medium text-mg-text",
                isActive ? "bg-mg-accent-soft text-mg-accent" : "hover:bg-mg-surface-2",
              )
            }
          >
            <Sparkles aria-hidden="true" size={18} />
            Trợ lý
          </NavLink>
        </li>
      </ul>
    </nav>
  );
}
