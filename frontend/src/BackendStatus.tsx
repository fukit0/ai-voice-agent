import { useEffect, useState } from "react";
import { fetchHealth, type Health } from "./api";

type State = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error"; message: string };

export function BackendStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    fetchHealth(ctrl.signal)
      .then((health) => setState({ kind: "ok", health }))
      .catch((err: Error) => {
        if (!ctrl.signal.aborted) setState({ kind: "error", message: err.message });
      });
    return () => ctrl.abort();
  }, []);

  const text =
    state.kind === "loading"
      ? "Backend kontrol ediliyor…"
      : state.kind === "ok"
        ? `Backend bağlı · v${state.health.version}`
        : `Backend yok (${state.message})`;
  return (
    <span className={`status status-${state.kind}`} data-testid="backend-status" role="status">
      {text}
    </span>
  );
}
