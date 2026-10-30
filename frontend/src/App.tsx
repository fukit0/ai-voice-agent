import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, Link } from "react-router-dom";
import { BackendStatus } from "./BackendStatus";
import { Icon } from "./icons";
import { ProfileProvider } from "./ProfileContext";
import { ProfileSelector } from "./ProfileSelector";
import { WarmupButton } from "./WarmupButton";
import { useTheme } from "./theme";
import { ScreenPlaceholder } from "./pages/ScreenPlaceholder";
import { ScenariosPage } from "./pages/ScenariosPage";
import { PersonaPage } from "./pages/PersonaPage";
import { PlaygroundPage } from "./pages/PlaygroundPage";
import { CallsPage } from "./pages/CallsPage";
import { MatrixPage } from "./pages/MatrixPage";
import { LlmEvalPage } from "./pages/LlmEvalPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SttPage } from "./pages/SttPage";
import { TtsPage } from "./pages/TtsPage";
import { NAV_GROUPS, SCREENS } from "./screens";
import "./theme.css";

// React Router v7 davranışlarını şimdiden aç (uyarıları kapatır, ileride geçişi kolaylaştırır).
export const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

const PAGES: Record<string, () => JSX.Element> = {
  "/overview": OverviewPage,
  "/stt": SttPage,
  "/llm": LlmEvalPage,
  "/scenarios": ScenariosPage,
  "/persona": PersonaPage,
  "/playground": PlaygroundPage,
  "/tts": TtsPage,
  "/calls": CallsPage,
  "/matrix": MatrixPage,
  "/settings": SettingsPage,
};

export function App() {
  const [theme, setTheme] = useTheme();
  const [drawer, setDrawer] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setDrawer(false), [pathname]);   // mobilde bir ekrana geçince çekmece kapanır

  return (
    <ProfileProvider>
      <div className={`layout${drawer ? " drawer-open" : ""}`}>
        <header className="topbar">
          <button type="button" className="icon-btn menu-btn" aria-label="Menü" aria-expanded={drawer}
            onClick={() => setDrawer((v) => !v)}>
            <Icon name={drawer ? "close" : "menu"} size={20} />
          </button>
          <div className="topbar-right">
            <BackendStatus />
            <ProfileSelector />
            <WarmupButton />
            <button type="button" className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={theme === "dark" ? "Açık tema" : "Koyu tema"} title={theme === "dark" ? "Açık tema" : "Koyu tema"}>
              <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
            </button>
            <Link to="/playground" className="cta"><Icon name="phone" size={16} /> Yeni Arama</Link>
          </div>
        </header>
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true"><Icon name="wave" size={16} /></span>
            <h1>Voice Agent Lab</h1>
            <span className="badge-demo">DEMO</span>
          </div>
          <nav aria-label="Lab ekranları">
            {NAV_GROUPS.map((g) => (
              <div className="nav-group" key={g}>
                <p className="nav-title">{g}</p>
                {SCREENS.filter((s) => s.group === g).map((s) => (
                  <NavLink key={s.path} to={s.path} className="nav-link">
                    <Icon name={s.icon} />
                    <span>{s.label}</span>
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
        </aside>
        <button type="button" className="scrim" aria-label="Menüyü kapat" tabIndex={-1} onClick={() => setDrawer(false)} />
        <main className="content">
          <Routes>
            <Route path="/" element={<Navigate to={SCREENS[0].path} replace />} />
            {SCREENS.map((s) => {
              const Page = PAGES[s.path];
              return <Route key={s.path} path={s.path} element={Page ? <Page /> : <ScreenPlaceholder screen={s} />} />;
            })}
            <Route path="*" element={<p>Sayfa bulunamadı.</p>} />
          </Routes>
        </main>
      </div>
    </ProfileProvider>
  );
}
