import { useCallback, useEffect, useRef, useState } from "react";
import { DEMO } from "../api/demo";
import { startSpeechSession } from "../api/endpoints";
import type { Lang } from "./i18n";
import { MAX_SESSION_MS, PcmResampler, TARGET_RATE, encodeAudioEvent, parseTranscriptMessage, speechSupported } from "./speech";

export type SpeechState = "idle" | "connecting" | "listening" | "finishing" | "denied" | "error";

const FLUSH_MS = 3000;

function openAudioContext(stream: MediaStream): AudioContext {
  try {
    const c = new AudioContext({ sampleRate: TARGET_RATE });
    c.createMediaStreamSource(stream);
    return c;
  } catch {
    return new AudioContext();
  }
}

type Session = { stop: () => void; abort: () => void };

export function useSpeechToText(lang: Lang, onFinal: (text: string) => void, onPartial: (text: string) => void) {
  const [state, setState] = useState<SpeechState>("idle");
  const session = useRef<Session | null>(null);
  const cb = useRef({ onFinal, onPartial });
  cb.current = { onFinal, onPartial };
  const supported = !DEMO && speechSupported();

  const stop = useCallback(() => session.current?.stop(), []);
  const abort = useCallback(() => session.current?.abort(), []);

  const start = useCallback(async () => {
    if (!supported || session.current) return;
    setState("connecting");
    let tracks: MediaStreamTrack[] = [];
    let ctx: AudioContext | null = null;
    let ws: WebSocket | null = null;
    let node: AudioWorkletNode | null = null;
    let timer = 0;
    let flushTimer = 0;
    let lastPartial = "";
    let ended = false;
    let finishing = false;

    const releaseAudio = () => {
      window.clearTimeout(timer);
      if (node) { node.port.onmessage = null; try { node.disconnect(); } catch {  } }
      tracks.forEach((t) => t.stop());
      tracks = [];
      if (ctx) { void ctx.close().catch(() => {}); ctx = null; }
    };
    const end = (next: SpeechState, keepText: boolean) => {
      if (ended) return;
      ended = true;
      window.clearTimeout(flushTimer);
      releaseAudio();
      if (ws) { ws.onclose = null; ws.onerror = null; ws.onmessage = null; try { ws.close(); } catch {  } }
      const rest = lastPartial.trim();
      lastPartial = "";
      cb.current.onPartial("");
      if (keepText && rest) cb.current.onFinal(rest);
      session.current = null;
      setState(next);
    };
    session.current = {
      stop: () => {
        if (finishing || ended) return;
        finishing = true;
        releaseAudio();
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(encodeAudioEvent(new Int16Array(0)));
          setState("finishing");
          flushTimer = window.setTimeout(() => end("idle", true), FLUSH_MS);
        } else end("idle", true);
      },
      abort: () => end("idle", false),
    };

    try {
      const s = await startSpeechSession(lang);
      if (ended) return;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      tracks = stream.getTracks();
      if (ended) { releaseAudio(); return; }
      ctx = openAudioContext(stream);
      await ctx.audioWorklet.addModule(`${import.meta.env.BASE_URL}pcm-worklet.js`);
      if (ended) { releaseAudio(); return; }
      const socket = new WebSocket(s.url);
      ws = socket;
      socket.binaryType = "arraybuffer";
      node = new AudioWorkletNode(ctx, "pcm-worklet");
      const resampler = new PcmResampler(ctx.sampleRate, s.sampleRate);
      node.port.onmessage = (e: MessageEvent<Float32Array>) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const pcm = resampler.process(e.data);
        if (pcm.length) socket.send(encodeAudioEvent(pcm));
      };
      ctx.createMediaStreamSource(stream).connect(node);
      socket.onopen = () => setState("listening");
      socket.onmessage = (e) => {
        const m = parseTranscriptMessage(new Uint8Array(e.data as ArrayBuffer));
        if (m.kind === "error") { end("error", true); return; }
        if (m.kind !== "transcript") return;
        if (m.isPartial) { lastPartial = m.text; cb.current.onPartial(m.text); }
        else { lastPartial = ""; cb.current.onPartial(""); cb.current.onFinal(m.text); }
      };
      socket.onerror = () => end("error", true);
      socket.onclose = () => end(finishing ? "idle" : "error", true);
      timer = window.setTimeout(() => session.current?.stop(), MAX_SESSION_MS);
    } catch (e) {
      const name = (e as { name?: string }).name;
      end(name === "NotAllowedError" || name === "SecurityError" ? "denied" : "error", false);
    }
  }, [lang, supported]);

  useEffect(() => () => { session.current?.abort(); }, []);
  return { state, supported, start, stop, abort };
}
