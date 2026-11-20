import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, usePoll } from "./api";
import Compare from "./pages/Compare";
import Experiments from "./pages/Experiments";
import Hardware from "./pages/Hardware";
import History from "./pages/History";
import Jobs from "./pages/Jobs";
import NewRun from "./pages/NewRun";
import RunDetail from "./pages/RunDetail";

const links: [string, string][] = [
  ["/new", "New run"],
  ["/jobs", "Jobs"],
  ["/history", "History"],
  ["/compare", "Compare"],
  ["/experiments", "Experiments"],
  ["/hardware", "Hardware"],
];

export default function App() {
  const { data: health, error } = usePoll(() => api<{ ok: boolean; queue: number; running: string[] }>("/api/health"), 4000);
  return (
    <div className="shell">
      <aside className="sidebar">
        <h1>psibench</h1>
        <p className="sub">PEPSI · VOLE-PSI · BZS-MPSI</p>
        {links.map(([to, label]) => (
          <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
            {label}
          </NavLink>
        ))}
        <div className="foot">
          {error ? (
            <span style={{ color: "#fca5a5" }}>API unreachable</span>
          ) : health ? (
            <>
              {health.running.length ? "● running" : "○ idle"}
              {health.queue ? ` · ${health.queue} queued` : ""}
            </>
          ) : (
            "connecting…"
          )}
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/new" replace />} />
          <Route path="/new" element={<NewRun />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<Jobs />} />
          <Route path="/history" element={<History />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="/hardware" element={<Hardware />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
