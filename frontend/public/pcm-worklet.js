class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Float32Array(4096);
    this.len = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        this.buf[this.len++] = ch[i];
        if (this.len === this.buf.length) {
          const out = this.buf;
          this.port.postMessage(out, [out.buffer]);
          this.buf = new Float32Array(4096);
          this.len = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("pcm-worklet", PcmWorklet);
