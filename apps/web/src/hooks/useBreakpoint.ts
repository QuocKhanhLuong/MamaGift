import { useSyncExternalStore } from "react";

export type Breakpoint = "mobile" | "tablet" | "desktop";

/** `docs/design/04_RESPONSIVE_STATES.md` section 2 breakpoint contract. */
function computeBreakpoint(width: number): Breakpoint {
  if (width >= 1200) return "desktop";
  if (width >= 768) return "tablet";
  return "mobile";
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("resize", callback);
  return () => window.removeEventListener("resize", callback);
}

export function useBreakpoint(): Breakpoint {
  return useSyncExternalStore(
    subscribe,
    () => computeBreakpoint(window.innerWidth),
    () => "desktop",
  );
}
