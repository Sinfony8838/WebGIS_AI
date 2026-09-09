/**
 * Shared audio downsampling core for the local ASR voice stream.
 *
 * The AudioWorklet in voiceStream.ts must resample whatever rate the
 * AudioContext runs at (44.1 / 48 / 16 kHz) down to 16 kHz. A naive
 * "integer counter" window (emit every ceil(ratio) samples) is silently
 * wrong at 44.1 kHz: ratio = 2.75625 rounds to an every-3-samples window,
 * producing an effective 14.7 kHz signal labelled as 16 kHz — ASR accuracy
 * collapses. The core below keeps the fractional remainder across windows
 * (phase carry), so the long-run output rate is exact: 80 samples at
 * 44.1 kHz produce exactly 29 output samples.
 *
 * The worklet source is built from the same ``RESAMPLER_CORE_SOURCE``
 * string that the unit tests evaluate, so tests exercise the algorithm that
 * actually ships instead of a drift-prone copy.
 */

export const TARGET_SAMPLE_RATE = 16000;
export const CHUNK_SAMPLES = 2048;

/** Fractional-phase averaging resampler (plain JS, worklet-compatible). */
export const RESAMPLER_CORE_SOURCE = `
class ResamplerCore {
  constructor(sourceRate, targetRate) {
    this.ratio = sourceRate / targetRate;
    this.acc = 0;
    this.window = 0;
  }
  push(sample) {
    this.acc += sample;
    this.window += 1;
    if (this.window >= this.ratio) {
      const out = Math.max(-1, Math.min(1, this.acc / this.window));
      this.acc = 0;
      this.window -= this.ratio;
      return out;
    }
    return null;
  }
}
`;

/** Rebuild the exact ResamplerCore class the worklet will run (test hook). */
export function loadResamplerCoreClass(): new (sourceRate: number, targetRate: number) => {
  push: (sample: number) => number | null;
  ratio: number;
} {
  const factory = new Function(`${RESAMPLER_CORE_SOURCE}; return ResamplerCore;`);
  return factory();
}

/** Full AudioWorklet source: ResamplerCore + float→PCM16 chunk batching. */
export function buildDownsamplerWorkletSource(): string {
  return `${RESAMPLER_CORE_SOURCE}
class PcmDownsampler extends AudioWorkletProcessor {
  constructor() {
    super();
    this.core = new ResamplerCore(sampleRate, ${TARGET_SAMPLE_RATE});
    this.chunk = new Float32Array(${CHUNK_SAMPLES});
    this.chunkPos = 0;
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel = input[0];
    for (let i = 0; i < channel.length; i++) {
      const out = this.core.push(channel[i]);
      if (out === null) continue;
      this.chunk[this.chunkPos++] = out;
      if (this.chunkPos >= this.chunk.length) {
        const pcm = new Int16Array(this.chunk.length);
        for (let j = 0; j < this.chunk.length; j++) {
          pcm[j] = this.chunk[j] < 0 ? this.chunk[j] * 0x8000 : this.chunk[j] * 0x7fff;
        }
        this.port.postMessage(pcm, [pcm.buffer]);
        this.chunkPos = 0;
      }
    }
    return true;
  }
}
try {
  registerProcessor("pcm-downsampler", PcmDownsampler);
} catch (error) {
  // Not inside an AudioWorkletGlobalScope (e.g. evaluated in a test run).
}
`;
}
