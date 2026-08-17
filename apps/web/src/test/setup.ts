import "@testing-library/jest-dom/vitest";
import { fetch, Headers, Request, Response } from "undici";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";

import { server } from "./server";

/**
 * Node's experimental global `localStorage` (unavailable without `--localstorage-file`)
 * shadows jsdom's own per-window implementation, so `window.localStorage` is otherwise
 * `undefined` here even though it exists in every real browser. A minimal in-memory
 * polyfill keeps this environment behaving like one.
 */
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

if (typeof window !== "undefined" && !window.localStorage) {
  Object.defineProperty(window, "localStorage", {
    value: new MemoryStorage(),
    writable: true,
    configurable: true,
  });
}

// jsdom's AbortController/AbortSignal are a distinct realm from the one Node's
// built-in fetch validates `signal` against, so an AbortController created in test
// code fails an `instanceof` check inside fetch. Re-pointing fetch (and its Headers/
// Request/Response) at undici, imported after jsdom has populated globals, makes both
// sides agree on the same AbortSignal class.
Object.defineProperties(globalThis, {
  fetch: { value: fetch, writable: true, configurable: true },
  Headers: { value: Headers, writable: true, configurable: true },
  Request: { value: Request, writable: true, configurable: true },
  Response: { value: Response, writable: true, configurable: true },
});

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => window.localStorage.clear());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
