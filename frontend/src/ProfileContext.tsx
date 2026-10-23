import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchProfiles, type ProfileStatus } from "./api";

// Seçili profil tüm Lab ekranlarında ortaktır; ekranlar backend'e bu profilin id'siyle istek atar
// (/api/profiles/{id}/stt|llm|tts). Seçim tarayıcıda hatırlanır.
const STORAGE_KEY = "sva.profile";

type ProfileState = {
  profiles: ProfileStatus[];
  active: ProfileStatus | null;
  setActiveId: (id: string) => void;
  error: string | null;
};

const Ctx = createContext<ProfileState>({ profiles: [], active: null, setActiveId: () => {}, error: null });

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function ProfileProvider({ children }: { children: ReactNode }) {
  const [profiles, setProfiles] = useState<ProfileStatus[]>([]);
  const [activeId, setActiveIdState] = useState<string | null>(readStored);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchProfiles(ctrl.signal)
      .then(setProfiles)
      .catch((err: Error) => {
        if (!ctrl.signal.aborted) setError(err.message);
      });
    return () => ctrl.abort();
  }, []);

  const value = useMemo<ProfileState>(() => {
    const active =
      profiles.find((p) => p.id === activeId) ?? profiles.find((p) => p.ready) ?? profiles[0] ?? null;
    return {
      profiles,
      active,
      error,
      setActiveId: (id: string) => {
        setActiveIdState(id);
        try {
          localStorage.setItem(STORAGE_KEY, id);
        } catch {
          /* tarayıcı depolaması kapalıysa seçim sadece bu oturumda kalır */
        }
      },
    };
  }, [profiles, activeId, error]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useProfile = () => useContext(Ctx);
