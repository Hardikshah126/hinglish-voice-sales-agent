"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  apiGet,
  apiPost,
  audioSrc,
  type AppConfig,
  type Latency,
  type Variant,
  type VoiceResponse,
} from "@/lib/api";
import { ms } from "@/lib/format";
import { useRecorder } from "@/hooks/useRecorder";
import { Card, ErrorNote, MockBanner, Skeleton } from "@/components/ui";

interface Message {
  id: number;
  speaker: "customer" | "agent";
  text: string;
  audioUrl?: string | null;
  speakable?: boolean; // spoken by the browser (free TTS) instead of a server audio file
}

type Phase = "idle" | "processing" | "speaking";

const SAMPLE_LINES = [
  "Hum abhi Excel pe leads manage karte hain.",
  "Price toh kaafi zyada lag raha hai yaar.",
  "Hum Zoho CRM use kar rahe hain already.",
  "Main sochke bataunga.",
];

/** A short silent WAV so the mock stack can be driven without a microphone. */
function silentWav(): Blob {
  const samples = 1600;
  const buffer = new ArrayBuffer(44 + samples * 2);
  const v = new DataView(buffer);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + samples * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, 8000, true);
  v.setUint32(28, 16000, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, samples * 2, true);
  return new Blob([buffer], { type: "audio/wav" });
}

export default function VoiceAgentPage() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [variant, setVariant] = useState<Variant>("persona");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [latency, setLatency] = useState<Latency | null>(null);
  const [turnCount, setTurnCount] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [typed, setTyped] = useState("");

  const recorder = useRecorder();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const idRef = useRef(0);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    apiGet<AppConfig>("/api/config")
      .then(setConfig)
      .catch((e: ApiError) => setConfigError(e.message));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, phase]);

  const play = useCallback((url: string) => {
    audioRef.current?.pause();
    const audio = new Audio(audioSrc(url));
    audioRef.current = audio;
    setPhase("speaking");
    audio.onended = () => setPhase("idle");
    audio.onerror = () => setPhase("idle");
    audio.play().catch(() => {
      setPhase("idle");
      setNotice("Your browser blocked autoplay. Press ▶ on the agent message to hear it.");
    });
  }, []);

  // Free TTS: the browser speaks the reply. Prefer an Indian-English voice, which reads
  // Roman-script Hinglish most naturally, then Hindi, then the browser default.
  const speak = useCallback((text: string) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      setNotice("This browser has no speech synthesis, so the reply is shown as text only.");
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const voices = window.speechSynthesis.getVoices();
    const voice = voices.find((v) => v.lang === "en-IN") ?? voices.find((v) => v.lang === "hi-IN");
    utterance.voice = voice ?? null;
    utterance.lang = voice?.lang ?? "en-IN";
    utterance.onstart = () => setPhase("speaking");
    utterance.onend = () => setPhase("idle");
    utterance.onerror = () => setPhase("idle");
    window.speechSynthesis.speak(utterance);
  }, []);

  const send = useCallback(
    async (audio: Blob, filename: string, override?: string) => {
      setPhase("processing");
      setError(null);
      setNotice(null);
      const form = new FormData();
      form.append("audio", audio, filename);
      form.append("prompt_variant", variant);
      if (conversationId) form.append("conversation_id", conversationId);
      if (override) form.append("transcript_override", override);
      try {
        const res = await apiPost<VoiceResponse>("/api/voice/respond", form);
        setConversationId(res.conversation_id);
        setLatency(res.latency);
        setTurnCount((n) => n + 1);
        setMessages((m) => [
          ...m,
          { id: ++idRef.current, speaker: "customer", text: res.transcript },
          {
            id: ++idRef.current,
            speaker: "agent",
            text: res.response_text,
            audioUrl: res.audio_url,
            speakable: res.speak_client_side,
          },
        ]);
        if (res.warnings.includes("tts_failed")) setNotice("Voice synthesis failed, so this reply is text only.");
        if (res.audio_url) play(res.audio_url);
        else if (res.speak_client_side) speak(res.response_text);
        else setPhase("idle");
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Something went wrong.");
        setPhase("idle");
      }
    },
    [variant, conversationId, play, speak],
  );

  const onPressStart = useCallback(() => {
    if (phase === "processing") return;
    audioRef.current?.pause();
    window.speechSynthesis?.cancel();
    setPhase("idle");
    void recorder.start();
  }, [phase, recorder]);

  const onPressEnd = useCallback(async () => {
    const clip = await recorder.stop();
    if (!clip) {
      setNotice("Didn't catch that. Hold the button for a moment while you speak.");
      return;
    }
    const ext = clip.blob.type.includes("mp4") ? "m4a" : clip.blob.type.includes("ogg") ? "ogg" : "webm";
    await send(clip.blob, `speech.${ext}`);
  }, [recorder, send]);

  const sendTyped = useCallback(
    (text: string) => {
      const line = text.trim();
      if (!line || phase === "processing") return;
      setTyped("");
      void send(silentWav(), "typed.wav", line);
    },
    [phase, send],
  );

  const changeVariant = (v: Variant) => {
    setVariant(v);
    setConversationId(null); // a conversation is bound to one prompt strategy
    setMessages([]);
    setLatency(null);
    setTurnCount(0);
    setNotice(null);
    setError(null);
  };

  const newConversation = () => changeVariant(variant);

  const recording = recorder.state === "recording";
  const busy = phase === "processing";
  const status = recording
    ? `Recording… ${(recorder.elapsedMs / 1000).toFixed(1)} s`
    : recorder.state === "starting"
      ? "Opening microphone…"
      : busy
        ? "Thinking…"
        : phase === "speaking"
          ? "Agent speaking…"
          : "Hold to speak";

  const mockParts = config?.mock_components ?? [];
  const isMock = mockParts.length > 0;
  const sttMock = mockParts.includes("stt");
  const activeVariant = config?.prompt_variants.find((p) => p.id === variant);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Hinglish Sales Agent</h1>
        <p className="mt-1 text-sm text-muted">
          Talk to a voice agent that sells FlowDesk, a CRM for small businesses, in natural Hinglish.
        </p>
      </div>

      {configError && <ErrorNote message={configError} />}
      {isMock && (
        <MockBanner>
          {mockParts.includes("llm") &&
            "No GROQ_API_KEY is configured, so agent replies come from a rule-based mock, not a language model. "}
          {sttMock && "Speech-to-text is mocked and returns a canned phrase; use the text box to send your own line. "}
          {mockParts.includes("tts") && "Voice output is a placeholder tone. "}
          Mocked parts are not representative of real quality or latency.
        </MockBanner>
      )}
      {config && !isMock && (
        <p className="text-xs text-muted">
          Live providers: LLM {config.components.llm.provider} ({config.components.llm.model}), STT{" "}
          {config.components.stt.provider} ({config.components.stt.model}), TTS{" "}
          {config.components.tts.client_side ? "browser speech synthesis" : `${config.components.tts.provider} (${config.components.tts.model})`}.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <div className="space-y-4">
          <Card title="Prompt strategy">
            {config ? (
              <>
                <label htmlFor="variant" className="sr-only">
                  Prompt strategy
                </label>
                <select
                  id="variant"
                  value={variant}
                  onChange={(e) => changeVariant(e.target.value as Variant)}
                  className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm"
                >
                  {config.prompt_variants.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.title}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-muted">{activeVariant?.description}</p>
                <p className="mt-1 text-xs text-muted">Changing strategy starts a fresh conversation.</p>
              </>
            ) : (
              <Skeleton className="h-9" />
            )}
          </Card>

          <Card>
            <div className="flex flex-col items-center gap-3 py-2">
              <button
                type="button"
                aria-pressed={recording}
                aria-label="Hold to speak"
                disabled={busy || !recorder.supported}
                onPointerDown={(e) => {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  onPressStart();
                }}
                onPointerUp={() => void onPressEnd()}
                onPointerCancel={() => void onPressEnd()}
                onKeyDown={(e) => {
                  if ((e.key === " " || e.key === "Enter") && !e.repeat) {
                    e.preventDefault();
                    onPressStart();
                  }
                }}
                onKeyUp={(e) => {
                  if (e.key === " " || e.key === "Enter") {
                    e.preventDefault();
                    void onPressEnd();
                  }
                }}
                onContextMenu={(e) => e.preventDefault()}
                className={`grid h-28 w-28 touch-none select-none place-items-center rounded-full text-4xl transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                  recording ? "recording-ring bg-danger text-white" : "bg-accent text-accent-fg hover:brightness-110"
                }`}
              >
                <span aria-hidden>{recording ? "●" : "🎙"}</span>
              </button>
              <div className="tabular text-sm font-medium" aria-live="polite">
                {status}
              </div>
              {!recorder.supported && (
                <p className="text-center text-xs text-muted">
                  This browser cannot record audio here. Open the app on
                  localhost/HTTPS in Chrome, Edge, Firefox or Safari.
                </p>
              )}
            </div>

            {recorder.error && <ErrorNote message={recorder.error} />}
            {error && <ErrorNote message={error} />}
            {notice && <p className="mt-2 text-center text-xs text-muted">{notice}</p>}

            {sttMock && (
              <div className="mt-4 border-t border-border pt-4">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    sendTyped(typed);
                  }}
                  className="flex gap-2"
                >
                  <input
                    value={typed}
                    onChange={(e) => setTyped(e.target.value)}
                    placeholder="Type what the customer says…"
                    maxLength={500}
                    aria-label="Type what the customer says"
                    className="min-w-0 flex-1 rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm"
                  />
                  <button
                    type="submit"
                    disabled={busy || !typed.trim()}
                    className="rounded-lg bg-accent px-3 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
                  >
                    Send
                  </button>
                </form>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {SAMPLE_LINES.map((line) => (
                    <button
                      key={line}
                      type="button"
                      disabled={busy}
                      onClick={() => sendTyped(line)}
                      className="rounded-full border border-border px-2.5 py-1 text-xs text-muted hover:bg-surface-2 hover:text-foreground disabled:opacity-50"
                    >
                      {line}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </Card>

          <Card title="Latency" action={<span className="text-xs text-muted">{turnCount} turn{turnCount === 1 ? "" : "s"}</span>}>
            {latency ? (
              <dl className="tabular grid grid-cols-[1fr_auto] gap-y-1.5 text-sm">
                <dt className="text-muted">STT</dt>
                <dd>{ms(latency.stt_ms)}</dd>
                <dt className="text-muted">LLM</dt>
                <dd>{ms(latency.llm_ms)}</dd>
                <dt className="text-muted">TTS</dt>
                <dd>{latency.tts_ms === null ? "in browser" : ms(latency.tts_ms)}</dd>
                <dt className="border-t border-border pt-1.5 font-semibold">Total</dt>
                <dd className="border-t border-border pt-1.5 font-semibold">{ms(latency.total_ms)}</dd>
              </dl>
            ) : (
              <p className="text-sm text-muted">Latency for your last turn appears here.</p>
            )}
            <p className="mt-3 text-xs text-muted">
              Measured live on the server with a monotonic clock for this real request
              {isMock ? ` (${mockParts.join("/").toUpperCase()} mocked, so those stages are near-zero)` : ""}. Browser
              speech synthesis is not timed. Benchmark latency is reported separately.
            </p>
          </Card>
        </div>

        <Card
          title="Conversation"
          action={
            messages.length > 0 && (
              <button type="button" onClick={newConversation} className="text-xs text-accent hover:underline">
                New conversation
              </button>
            )
          }
          className="min-h-[420px]"
        >
          <div className="flex max-h-[62vh] min-h-[340px] flex-col gap-3 overflow-y-auto pr-1" aria-live="polite">
            {messages.length === 0 && !busy && (
              <div className="m-auto max-w-sm text-center text-sm text-muted">
                Hold the microphone and say something like
                <div className="mt-2 rounded-lg bg-surface-2 px-3 py-2 text-foreground">
                  “Hum abhi Excel pe leads manage karte hain.”
                </div>
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`flex ${m.speaker === "customer" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${
                    m.speaker === "customer"
                      ? "rounded-br-sm bg-accent text-accent-fg"
                      : "rounded-bl-sm border border-border bg-surface-2"
                  }`}
                >
                  <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wide opacity-70">
                    {m.speaker === "customer" ? "Customer" : "Agent"}
                  </div>
                  {m.text}
                  {m.speaker === "agent" && (m.audioUrl || m.speakable) && (
                    <button
                      type="button"
                      onClick={() => (m.audioUrl ? play(m.audioUrl) : speak(m.text))}
                      aria-label="Play agent reply"
                      className="ml-2 align-middle text-xs text-muted hover:text-foreground"
                    >
                      ▶
                    </button>
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <div className="flex justify-start">
                <div className="rounded-2xl rounded-bl-sm border border-border bg-surface-2 px-3.5 py-2 text-sm text-muted">
                  Agent is thinking…
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        </Card>
      </div>
    </div>
  );
}
