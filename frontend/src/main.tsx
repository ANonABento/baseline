import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { usePath } from "./lib/prefs";
import { CallPage } from "./pages/CallPage";
import { Landing } from "./pages/Landing";
import { Report, Reports } from "./pages/Report";

function App() {
  const path = usePath().replace(/\/+$/, "") || "/";
  if (path === "/") return <Landing />;
  if (path === "/call") return <CallPage />;
  if (path === "/reports") return <Reports />;
  const m = path.match(/^\/report\/([^/]+)$/);
  if (m) return <Report key={m[1]} id={decodeURIComponent(m[1])} />;
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
