import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { BackendStatus } from "./BackendStatus";
import { ProfileProvider } from "./ProfileContext";
import { ProfileSelector } from "./ProfileSelector";
import { WarmupButton } from "./WarmupButton";
import { ScreenPlaceholder } from "./pages/ScreenPlaceholder";
import { SttPage } from "./pages/SttPage";
import { TtsPage } from "./pages/TtsPage";
import { SCREENS } from "./screens";

// React Router v7 davranışlarını şimdiden aç (uyarıları kapatır, ileride geçişi kolaylaştırır).
export const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

export function App() {
  return (
    <ProfileProvider>
    <div className="layout">
      <header className="topbar">
        <h1>Voice Agent Lab</h1>
        <div className="topbar-right">
          <ProfileSelector />
          <WarmupButton />
          <BackendStatus />
        </div>
      </header>
      <nav aria-label="Lab ekranları" className="sidebar">
        {SCREENS.map((s) => (
          <NavLink key={s.path} to={s.path}>
            {s.label}
          </NavLink>
        ))}
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to={SCREENS[0].path} replace />} />
          {SCREENS.map((s) => (
            <Route key={s.path} path={s.path}
              element={s.path === "/stt" ? <SttPage /> : s.path === "/tts" ? <TtsPage /> : <ScreenPlaceholder screen={s} />} />
          ))}
          <Route path="*" element={<p>Sayfa bulunamadı.</p>} />
        </Routes>
      </main>
    </div>
    </ProfileProvider>
  );
}
