import { useCallback, useEffect, useState } from "react";

// Tema tercihi (ui-001): koyu varsayılan (referans arayüz gibi), açık seçilebilir. Tercih yalnız bu tarayıcıda saklanır;
// localStorage erişimi kapalı olabilir (gizli pencere), bu yüzden her okuma/yazma try/catch içindedir.
export type Theme = "dark" | "light";
const KEY = "sva.theme";

export function readTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark") return v;
  } catch { /* yok */ }
  return "dark";
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readTheme);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try { localStorage.setItem(KEY, t); } catch { /* yok */ }
  }, []);
  return [theme, setTheme];
}
