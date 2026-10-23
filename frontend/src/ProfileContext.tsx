import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchProfiles, getWarmup, startWarmup, type ProfileStatus, type WarmupJob } from "./api";

// Seçili profil tüm Lab ekranlarında ortaktır; ekranlar backend'e bu profilin id'siyle istek atar
// (/api/profiles/{id}/stt|llm|tts). Seçim tarayıcıda hatırlanır.
const STORAGE_KEY = "sva.profile";

type ProfileState = {
  profiles: ProfileStatus[];
  active: ProfileStatus | null;
  setActiveId: (id: string) => void;
  error: string | null;
  /** Aktif profilin süren/son hazırlama işi */
  job: WarmupJob | null;
  prepare: () => Promise<void>;
  prepareError: string | null;
};

const Ctx = createContext<ProfileState>({
  profiles: [],
  active: null,
  setActiveId: () => {},
  error: null,
  job: null,
  prepare: async () => {},
  prepareError: null,
});

const POLL_MS = 1000;

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
  const [job, setJob] = useState<WarmupJob | null>(null);
  const [prepareError, setPrepareError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchProfiles(ctrl.signal)
      .then(setProfiles)
      .catch((err: Error) => {
        if (!ctrl.signal.aborted) setError(err.message);
      });
    return () => ctrl.abort();
  }, [reload]);

  // Süren hazırlamayı izle; bitince profil durumlarını (sıcak/soğuk) yenile.
  useEffect(() => {
    if (job?.state !== "running") return;
    const id = setTimeout(() => {
      getWarmup(job.profile)
        .then((next) => {
          setJob(next);
          if (next.state !== "running") setReload((n) => n + 1);
        })
        .catch((err: Error) => setPrepareError(err.message));
    }, POLL_MS);
    return () => clearTimeout(id);
  }, [job]);

  const value = useMemo<ProfileState>(() => {
    const active =
      profiles.find((p) => p.id === activeId) ?? profiles.find((p) => p.ready) ?? profiles[0] ?? null;
    const activeJob = job && active && job.profile === active.id ? job : (active?.warmup ?? null);
    return {
      profiles,
      active,
      error,
      job: activeJob,
      prepareError,
      prepare: async () => {
        if (!active) return;
        setPrepareError(null);
        try {
          setJob(await startWarmup(active.id));
        } catch (err) {
          setPrepareError((err as Error).message);
        }
      },
      setActiveId: (id: string) => {
        setPrepareError(null);
        setActiveIdState(id);
        try {
          localStorage.setItem(STORAGE_KEY, id);
        } catch {
          /* tarayıcı depolaması kapalıysa seçim sadece bu oturumda kalır */
        }
      },
    };
  }, [profiles, activeId, error, job, prepareError]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useProfile = () => useContext(Ctx);
