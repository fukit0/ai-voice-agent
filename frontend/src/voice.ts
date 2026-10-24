// Tarayıcıdan mikrofonla ajanla konuşma (core-001): WebRTC ile backend'e bağlanır.
// Yerel kullanım: STUN/TURN yok (iceServers boş), ICE tamamlanınca tek seferde teklif gönderilir.

export type VoiceEvent =
  | { type: "state"; state: "idle" | "listening" | "thinking" | "speaking" | "closed" }
  | { type: "transcript"; role: "user" | "agent"; text: string; t: number }
  | { type: "turn"; turn: number; stt_s?: number; llm_s?: number; tts_first_s?: number; first_audio_after_end_s?: number;
      endpoint_wait_ms?: number; user_seconds?: number; greeting?: boolean }
  | { type: "barge_in" }
  | { type: "error"; message: string };

export type VoiceHooks = {
  onEvent: (e: VoiceEvent) => void;
  onLevels?: (mic: number, agent: number) => void; // 0..1
};

export type VoiceHandle = { sessionId: string; close: () => Promise<void> };

const MIC_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1,
};

function waitIce(pc: RTCPeerConnection, timeoutMs = 3000): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => { pc.removeEventListener("icegatheringstatechange", check); clearTimeout(timer); resolve(); };
    const check = () => { if (pc.iceGatheringState === "complete") done(); };
    const timer = setTimeout(done, timeoutMs);
    pc.addEventListener("icegatheringstatechange", check);
  });
}

function rms(analyser: AnalyserNode, buf: Float32Array): number {
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (const v of buf) sum += v * v;
  return Math.sqrt(sum / buf.length);
}

export async function startVoice(profile: string, hooks: VoiceHooks): Promise<VoiceHandle> {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("Bu tarayıcı mikrofon erişimini desteklemiyor (HTTPS veya localhost gerekir).");
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: MIC_CONSTRAINTS });
  } catch {
    throw new Error("Mikrofona erişilemedi. Tarayıcı izin penceresinde izin verin ya da adres çubuğundan mikrofon iznini açın.");
  }
  const pc = new RTCPeerConnection({ iceServers: [] });
  const channel = pc.createDataChannel("events");
  channel.onmessage = (m) => {
    try { hooks.onEvent(JSON.parse(m.data) as VoiceEvent); } catch { /* bozuk olay yok sayılır */ }
  };
  stream.getTracks().forEach((t) => pc.addTrack(t, stream));

  const audio = new Audio();
  audio.autoplay = true;
  const ctx = new AudioContext();
  const micAn = ctx.createAnalyser();
  ctx.createMediaStreamSource(stream).connect(micAn);
  let agentAn: AnalyserNode | null = null;
  pc.ontrack = (e) => {
    const remote = e.streams[0] ?? new MediaStream([e.track]);
    audio.srcObject = remote;
    void audio.play().catch(() => {});
    agentAn = ctx.createAnalyser();
    ctx.createMediaStreamSource(remote).connect(agentAn);
  };

  const bufM = new Float32Array(micAn.fftSize);
  const stats = { remotePeak: 0, remoteSamples: 0 };
  (window as unknown as { __voiceStats?: typeof stats }).__voiceStats = stats; // e2e doğrulaması: ajan sesi gerçekten alındı mı
  const meter = setInterval(() => {
    const a = agentAn ? rms(agentAn, new Float32Array(agentAn.fftSize)) : 0;
    stats.remotePeak = Math.max(stats.remotePeak, a);
    if (a > 0.001) stats.remoteSamples += 1;
    hooks.onLevels?.(Math.min(1, rms(micAn, bufM) * 4), Math.min(1, a * 4));
  }, 100);

  const cleanup = async () => {
    clearInterval(meter);
    stream.getTracks().forEach((t) => t.stop());
    audio.srcObject = null;
    pc.close();
    await ctx.close().catch(() => {});
  };

  try {
    await pc.setLocalDescription(await pc.createOffer());
    await waitIce(pc);
    const res = await fetch("/api/voice/offer", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sdp: pc.localDescription!.sdp, type: pc.localDescription!.type, profile }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.detail?.message ?? `Bağlantı kurulamadı (HTTP ${res.status}).`);
    }
    const answer = (await res.json()) as { session_id: string; sdp: string; type: RTCSdpType };
    await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
        hooks.onEvent({ type: "error", message: "Bağlantı koptu." });
        hooks.onEvent({ type: "state", state: "closed" });
      }
    };
    return {
      sessionId: answer.session_id,
      close: async () => {
        await fetch(`/api/voice/${answer.session_id}`, { method: "DELETE" }).catch(() => {});
        await cleanup();
      },
    };
  } catch (e) {
    await cleanup();
    throw e;
  }
}
