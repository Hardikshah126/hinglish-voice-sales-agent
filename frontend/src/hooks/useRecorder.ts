"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type RecorderState = "idle" | "starting" | "recording";

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const MIN_RECORDING_MS = 400;

export interface Recording {
  blob: Blob;
  durationMs: number;
}

/**
 * Hold-to-speak microphone recorder.
 * `start()` may resolve after the user already released the button; `stop()` called in
 * that window cancels cleanly instead of leaving the microphone open.
 */
export function useRecorder() {
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef(0);
  const wantRecordingRef = useRef(false);
  const resolveStopRef = useRef<((r: Recording | null) => void) | null>(null);

  const supported =
    typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    if (state !== "recording") return;
    const id = window.setInterval(() => setElapsedMs(Date.now() - startedAtRef.current), 100);
    return () => window.clearInterval(id);
  }, [state]);

  useEffect(() => () => releaseStream(), [releaseStream]);

  const start = useCallback(async () => {
    if (!supported) {
      setError("Microphone recording is not supported in this browser (or the page is not served over HTTPS/localhost).");
      return;
    }
    setError(null);
    wantRecordingRef.current = true;
    setState("starting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (!wantRecordingRef.current) {
        stream.getTracks().forEach((t) => t.stop()); // released before the mic was ready
        setState("idle");
        return;
      }
      streamRef.current = stream;
      const mimeType = MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      recorder.onstop = () => {
        const durationMs = Date.now() - startedAtRef.current;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || mimeType || "audio/webm" });
        releaseStream();
        setState("idle");
        setElapsedMs(0);
        const resolve = resolveStopRef.current;
        resolveStopRef.current = null;
        resolve?.(durationMs >= MIN_RECORDING_MS && blob.size > 0 ? { blob, durationMs } : null);
      };
      recorderRef.current = recorder;
      startedAtRef.current = Date.now();
      recorder.start();
      setState("recording");
    } catch (e) {
      wantRecordingRef.current = false;
      releaseStream();
      setState("idle");
      const name = e instanceof DOMException ? e.name : "";
      setError(
        name === "NotAllowedError"
          ? "Microphone permission was denied. Allow it in the browser address bar and try again."
          : name === "NotFoundError"
            ? "No microphone was found."
            : "Could not start the microphone.",
      );
    }
  }, [supported, releaseStream]);

  /** Stops recording; resolves with the clip, or null if it was too short / cancelled. */
  const stop = useCallback((): Promise<Recording | null> => {
    wantRecordingRef.current = false;
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return Promise.resolve(null);
    return new Promise((resolve) => {
      resolveStopRef.current = resolve;
      recorder.stop();
    });
  }, []);

  return { state, error, elapsedMs, supported, start, stop, clearError: () => setError(null) };
}
