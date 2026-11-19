// Pure helpers for push-to-talk (task 5.1): browser mic floats -> 16 kHz PCM16 for the Caller.

export const MIC_RATE = 16000;

/** Average-downsample mono floats from ``fromRate`` to ``toRate`` (``toRate`` <= ``fromRate``). */
export function downsample(input: Float32Array, fromRate: number, toRate = MIC_RATE): Float32Array {
  if (fromRate === toRate) return input;
  if (toRate > fromRate) throw new Error("upsampling is not supported");
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return out;
}

/** Floats in [-1, 1] to little-endian signed 16-bit PCM (clipped). */
export function floatToPcm16(input: Float32Array): ArrayBuffer {
  const buf = new ArrayBuffer(input.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, s < 0 ? Math.round(s * 32768) : Math.round(s * 32767), true);
  }
  return buf;
}

/**
 * Collects worklet frames (128 samples each at the context rate) and emits ~``chunkMs`` PCM16
 * chunks at 16 kHz, carrying the remainder so no samples are lost between chunks.
 */
export class MicChunker {
  private pending: number[] = [];
  readonly fromRate: number;
  readonly chunkSamples: number;

  constructor(fromRate: number, chunkMs = 100) {
    this.fromRate = fromRate;
    this.chunkSamples = Math.round((fromRate * chunkMs) / 1000);
  }

  push(frame: Float32Array): ArrayBuffer[] {
    for (const x of frame) this.pending.push(x);
    const out: ArrayBuffer[] = [];
    while (this.pending.length >= this.chunkSamples) {
      const block = Float32Array.from(this.pending.splice(0, this.chunkSamples));
      out.push(floatToPcm16(downsample(block, this.fromRate)));
    }
    return out;
  }

  flush(): ArrayBuffer | null {
    if (!this.pending.length) return null;
    const block = Float32Array.from(this.pending.splice(0));
    return floatToPcm16(downsample(block, this.fromRate));
  }
}
