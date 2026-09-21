import { useEffect, useState } from "react";

type Health = {
  status: string;
  service: string;
  version: string;
  environment: string;
};

type ApiState =
  | { kind: "checking" }
  | { kind: "online"; health: Health }
  | { kind: "offline" };

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const flow = ["Intent", "Plan", "Execute", "Verify", "Capture", "Render"];

function App() {
  const [apiState, setApiState] = useState<ApiState>({ kind: "checking" });

  useEffect(() => {
    const controller = new AbortController();

    async function checkApi() {
      try {
        const response = await fetch(`${apiBaseUrl}/health`, {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Health request failed with ${response.status}`);
        }
        const health = (await response.json()) as Health;
        setApiState({ kind: "online", health });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setApiState({ kind: "offline" });
      }
    }

    void checkApi();
    return () => controller.abort();
  }, []);

  const statusLabel =
    apiState.kind === "checking"
      ? "Checking API"
      : apiState.kind === "online"
        ? `API online · v${apiState.health.version}`
        : "API offline · start the backend";

  return (
    <main>
      <nav aria-label="Product">
        <a className="brand" href="/" aria-label="ProofDemo home">
          <span className="brand-mark" aria-hidden="true">
            P
          </span>
          ProofDemo
        </a>
        <span className={`status status-${apiState.kind}`}>
          <span className="status-dot" aria-hidden="true" />
          {statusLabel}
        </span>
      </nav>

      <section className="hero">
        <p className="eyebrow">Verified product storytelling</p>
        <h1>Demo what happened.<br />Prove that it worked.</h1>
        <p className="lede">
          ProofDemo turns product intent into structured, replayable demos where
          every important claim is tied to observable evidence.
        </p>
        <div className="stage-card">
          <div>
            <span className="stage-label">Current build</span>
            <strong>Stage 0 · Foundation</strong>
          </div>
          <p>Contracts, lifecycle, API, and local development are ready for deterministic execution.</p>
        </div>
      </section>

      <section className="flow" aria-label="ProofDemo product flow">
        {flow.map((step, index) => (
          <div className={index < 2 ? "flow-step flow-step-active" : "flow-step"} key={step}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{step}</strong>
          </div>
        ))}
      </section>

      <footer>
        <span>Deterministic by default</span>
        <span>Evidence before polish</span>
      </footer>
    </main>
  );
}

export default App;
