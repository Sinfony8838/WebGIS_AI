import { describe, expect, it } from "vitest";
import { buildDownsamplerWorkletSource, loadResamplerCoreClass, TARGET_SAMPLE_RATE } from "../voiceResampler";

// 直接求值 worklet 内嵌的同一段算法源码，保证测试覆盖的就是线上运行的实现。
const ResamplerCore = loadResamplerCoreClass();

describe("ResamplerCore（分数相位降采样）", () => {
  it("16 kHz 直通：逐样本输出，不丢失", () => {
    const core = new ResamplerCore(16000, 16000);
    let count = 0;
    for (let i = 0; i < 500; i++) {
      if (core.push(i % 2 === 0 ? 0.5 : -0.5) !== null) count += 1;
    }
    expect(count).toBe(500);
  });

  it("48 kHz：每 3 个样本平均输出一次，幅度一致", () => {
    const core = new ResamplerCore(48000, 16000);
    const out: number[] = [];
    for (let i = 0; i < 3000; i++) {
      const v = core.push(0.5);
      if (v !== null) out.push(v);
    }
    expect(out).toHaveLength(1000);
    out.forEach((v) => expect(v).toBeCloseTo(0.5, 5));
  });

  it("44.1 kHz：长周期输出率精确（旧整数累计算法会少 8% 而被标成 16 kHz）", () => {
    const core = new ResamplerCore(44100, 16000);
    let out = 0;
    for (let i = 0; i < 8000; i++) {
      if (core.push(0.25) !== null) out += 1;
    }
    // 8000 / (44100/16000) = 2902.49…，相位进位后应精确落在 ±1 内。
    expect(out).toBeGreaterThanOrEqual(2901);
    expect(out).toBeLessThanOrEqual(2903);
  });

  it("44.1 kHz 正弦保真：1 kHz 输入的输出频率误差 < 1%", () => {
    const rate = 44100;
    const freq = 1000;
    const core = new ResamplerCore(rate, TARGET_SAMPLE_RATE);
    const out: number[] = [];
    for (let i = 0; i < rate; i++) {
      const v = core.push(Math.sin((2 * Math.PI * freq * i) / rate));
      if (v !== null) out.push(v);
    }
    let crossings = 0;
    for (let i = 1; i < out.length; i++) {
      if (out[i - 1] < 0 && out[i] >= 0) crossings += 1;
    }
    const estimated = (crossings * TARGET_SAMPLE_RATE) / out.length;
    expect(Math.abs(estimated - freq) / freq).toBeLessThan(0.01);
  });
});

describe("worklet 源码", () => {
  it("内嵌同一 ResamplerCore 算法且语法可解析", () => {
    const source = buildDownsamplerWorkletSource();
    expect(source).toContain("class ResamplerCore");
    expect(source).toContain("registerProcessor(\"pcm-downsampler\", PcmDownsampler)");
    expect(() => new Function(source)).not.toThrow();
  });
});
