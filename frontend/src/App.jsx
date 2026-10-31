import { useEffect, useState } from "react";
import { UserContext } from "./user.js";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { getHealth, getMe, getStats, logout } from "./api.js";
import Login from "./pages/Login.jsx";
import CommandPalette from "./components/CommandPalette.jsx";
import {
  IconChat, IconDashboard, IconFile, IconInbox, IconMonitor, IconMoon, IconReview, IconSearch, IconSun, Logo,
} from "./icons.jsx";
import Ask from "./pages/Ask.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import DocumentDetail from "./pages/DocumentDetail.jsx";
import Documents from "./pages/Documents.jsx";
import Reviews from "./pages/Reviews.jsx";
import Settings from "./pages/Settings.jsx";
import { can } from "./user.js";
import { useTheme } from "./theme.js";

const SERVICES = [
  ["database", "Database"],
  ["redis", "Job queue"],
  ["llm", "Local LLM"],
];
const THEME_ICON = { system: IconMonitor, light: IconSun, dark: IconMoon };

// Service status and review count, refreshed every 15 seconds.
function useSidebarData() {
  const [health, setHealth] = useState(null);
  const [pending, setPending] = useState(0);
  useEffect(() => {
    const load = () => {
      getHealth().then(setHealth, () => setHealth({}));
      getStats().then((s) => setPending(s.pending_reviews), () => {});
    };
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);
  return { health, pending };
}

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = still checking, null = signed out

  useEffect(() => {
    getMe().then(setUser, () => setUser(null));
    const signedOut = () => setUser(null);
    window.addEventListener("veritas:signed-out", signedOut);
    return () => window.removeEventListener("veritas:signed-out", signedOut);
  }, []);

  if (user === undefined) return <div className="login-page"><div className="skeleton" style={{ width: 240 }} /></div>;
  if (user === null) return <Login onSignedIn={setUser} />;
  return (
    <UserContext.Provider value={user}>
      <Shell user={user} onSignOut={() => logout().finally(() => setUser(null))} />
    </UserContext.Provider>
  );
}

function Shell({ user, onSignOut }) {
  const { health, pending } = useSidebarData();
  const { theme, next } = useTheme();
  const location = useLocation();
  const ThemeIcon = THEME_ICON[theme];
  const nav = [
    ["/", "Dashboard", IconDashboard],
    ["/documents", "Documents", IconFile],
    ["/reviews", "Reviews", IconReview, pending],
    ["/ask", "Ask documents", IconChat],
    ...(can(user, "admin") ? [["/settings", "Settings", IconInbox]] : []),
  ];

  // Braces matter: newer browsers make scrollTo() return a Promise, and an effect
  // that returns anything other than a cleanup function crashes React.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <Logo />
          <div>
            <strong>Veritas AI</strong>
            <span>Document verification</span>
          </div>
        </div>
        <button className="search-button"
                onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }))}>
          <IconSearch size={16} /> Search… <kbd>Ctrl K</kbd>
        </button>
        <nav>
          {nav.map(([to, label, Icon, count]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              <Icon /> {label}
              {count > 0 && <span key={count} className="nav-count">{count}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="status">
            <span className="status-title">Services</span>
            {SERVICES.map(([key, label]) => (
              <span key={key} className="status-row">
                <span className={`dot ${health ? (health[key] ? "on" : "off") : ""}`} />
                {label}
              </span>
            ))}
          </div>
          <button className="theme-button" onClick={next} title="Change theme">
            <ThemeIcon size={16} /> {theme.charAt(0).toUpperCase() + theme.slice(1)} theme
          </button>
          <div className="user-box">
            <div>
              <strong>{user.name}</strong>
              <span>{user.role} · {user.organization_name}</span>
            </div>
            <button className="link" onClick={onSignOut}>Sign out</button>
          </div>
        </div>
      </aside>
      <main className="content">
        {/* A new key on every route change replays the page-enter animation. */}
        <div key={location.pathname} className="page">
          <Routes location={location}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/documents" element={<Documents />} />
            <Route path="/documents/:id" element={<DocumentDetail />} />
            <Route path="/reviews" element={<Reviews />} />
            <Route path="/ask" element={<Ask />} />
            {can(user, "admin") && <Route path="/settings" element={<Settings />} />}
          </Routes>
        </div>
      </main>
      <CommandPalette />
    </div>
  );
}
