import { useEffect, useState } from "react";

type HealthResponse = {
  status: "ok";
  service: "api";
  version: string;
};

type HealthState =
  | { kind: "loading" }
  | { kind: "ready"; response: HealthResponse }
  | { kind: "error"; message: string };

const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export function App() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${apiUrl}/health`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`API returned ${response.status}`);
        }
        return (await response.json()) as HealthResponse;
      })
      .then((response) => setHealth({ kind: "ready", response }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setHealth({ kind: "error", message: "Không thể kết nối API." });
      });

    return () => controller.abort();
  }, []);

  return (
    <main className="health-page">
      <section className="health-card" aria-labelledby="health-title">
        <p className="eyebrow">MamaGift · Nền tảng</p>
        <h1 id="health-title">Nền tảng đang được kiểm tra</h1>
        <p className="lede">
          Đây là màn hình sức khỏe tối thiểu của nền tảng. Các luồng văn bản sẽ được xây dựng sau.
        </p>
        <div className="status-row" aria-live="polite" role="status">
          <span className={`status-dot status-${health.kind}`} aria-hidden="true" />
          {health.kind === "loading" && "Đang kiểm tra API…"}
          {health.kind === "error" && health.message}
          {health.kind === "ready" && `API hoạt động · phiên bản ${health.response.version}`}
        </div>
      </section>
    </main>
  );
}
