import { EventStreamCodec } from "@smithy/eventstream-codec";
import { fromUtf8, toUtf8 } from "@smithy/util-utf8";

export const TARGET_RATE = 16000;
export const MAX_SESSION_MS = 60_000;

const codec = new EventStreamCodec(toUtf8, fromUtf8);

export class PcmResampler {
  private readonly step: number;
  private acc = 0;
  private need: number;
  constructor(inRate: number, outRate = TARGET_RATE) { this.step = inRate / outRate; this.need = this.step; }

  process(chunk: Float32Array): Int16Array {
    const out: number[] = [];
    for (let n = 0; n < chunk.length; n++) {
      let left = 1;
      while (left > 1e-9) {
        const take = Math.min(left, this.need);
        this.acc += chunk[n] * take;
        this.need -= take;
        left -= take;
        if (this.need <= 1e-9) {
          const x = Math.max(-1, Math.min(1, this.acc / this.step));
          out.push(Math.round(x * (x < 0 ? 0x8000 : 0x7fff)));
          this.acc = 0;
          this.need = this.step;
        }
      }
    }
    return Int16Array.from(out);
  }
}

export function encodeAudioEvent(pcm: Int16Array): Uint8Array {
  const body = new Uint8Array(pcm.length * 2);
  const view = new DataView(body.buffer);
  pcm.forEach((s, i) => view.setInt16(i * 2, s, true));
  return codec.encode({
    headers: {
      ":message-type": { type: "string", value: "event" },
      ":event-type": { type: "string", value: "AudioEvent" },
      ":content-type": { type: "string", value: "application/octet-stream" },
    },
    body,
  });
}

export type TranscriptMessage =
  | { kind: "transcript"; text: string; isPartial: boolean }
  | { kind: "error"; message: string }
  | { kind: "ignored" };

export function parseTranscriptMessage(data: Uint8Array): TranscriptMessage {
  const msg = codec.decode(data);
  const type = msg.headers[":message-type"]?.value;
  let payload: unknown = {};
  try { payload = JSON.parse(toUtf8(msg.body)); } catch {  }
  if (type === "exception") {
    const m = (payload as { Message?: string }).Message;
    return { kind: "error", message: m ?? String(msg.headers[":exception-type"]?.value ?? "exception") };
  }
  const r = (payload as { Transcript?: { Results?: { IsPartial: boolean; Alternatives?: { Transcript?: string }[] }[] } })
    .Transcript?.Results?.[0];
  const text = r?.Alternatives?.[0]?.Transcript;
  if (!r || text === undefined) return { kind: "ignored" };
  return { kind: "transcript", text, isPartial: r.IsPartial };
}

export function speechSupported(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia
    && typeof AudioWorkletNode !== "undefined" && typeof WebSocket !== "undefined";
}

export function appendSpeech(current: string, segment: string, max: number): string {
  const s = segment.trim();
  if (!s) return current;
  return (current && !/\s$/.test(current) ? `${current} ${s}` : `${current}${s}`).slice(0, max);
}
