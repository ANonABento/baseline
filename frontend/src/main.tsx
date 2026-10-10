import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { usePath } from "./lib/prefs";
import { CallPage } from "./pages/CallPage";
import { Landing } from "./pages/Landing";
import { Report, Reports } from "./pages/Report";

// The v1 agent dashboard, kept reachable (and its Tailwind CSS isolated) behind a lazy chunk.
const Legacy = lazy(() => import("./legacy/App"));

function App() {
  const path = usePath().replace(/\/+$/, "") || "/";
  if (path === "/") return <Landing />;
  if (path === "/call") return <CallPage />;
  if (path === "/reports") return <Reports />;
  const m = path.match(/^\/report\/([^/]+)$/);
  if (m) return <Report key={m[1]} id={decodeURIComponent(m[1])} />;
  if (path === "/legacy")
    return (
      <Suspense fallback={null}>
        <Legacy />
      </Suspense>
    );
  return (
    <div className="notice">
      <span className="label">404</span>
      <h1 className="section__title">Nothing on this line.</h1>
      <p>
        <a className="link" href="/">
          Back to Baseline
        </a>
      </p>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
