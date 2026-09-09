"""WS 音频注入验收：把 SAPI 合成的指令 WAV 灌进真实 /assistant/voice/stream，
验证 partial/final 真实返回并统计「说完→final」延迟。

用法：python scratch/acceptance_audio/ws_inject.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np
import websockets

WS_URL = "ws://127.0.0.1:18990/assistant/voice/stream"
AUDIO_DIR = Path(__file__).resolve().parent
CHUNK_SAMPLES = 2048  # 与前端 worklet 一致（~128ms @16k）
EXPECT = {
    "01_globe": "切换到三维地球",
    "02_plane": "二维",
    "03_open_layers": "图层",
    "04_close_layers": "图层",
    "05_opacity": "透明",
    "06_fly": "长三角",
    "07_next_stage": "环节",
    "08_start_class": "上课",
    "09_wake_globe": "三维",
    "10_end_class": "上课",
    "11_chatter": None,  # 负向对照：闲聊，final 可能为空或无指令词
    "12_negated": None,  # 负向对照：否定表达，转写仍会出现
}


def load_wav_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    assert width == 2, f"expect PCM16, got sampwidth={width}"
    samples = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if rate != 16000:
        count = int(len(samples) * 16000 / rate)
        indices = np.linspace(0, len(samples) - 1, count)
        samples = np.interp(indices, np.arange(len(samples)), samples.astype(np.float64)).astype(np.int16)
    return samples


async def inject_one(name: str, wav_path: Path) -> dict:
    samples = load_wav_16k(wav_path)
    partials: list[str] = []
    finals: list[str] = []
    events: list[dict] = []
    t_start = time.perf_counter()
    async with websockets.connect(WS_URL, max_size=2**22) as ws:
        t_connected = time.perf_counter()
        # 按 128ms/块的实时节奏发送（端点检测依赖真实时间静音）。
        receiver = asyncio.create_task(_collect(ws, partials, finals, events))
        for i in range(0, len(samples), CHUNK_SAMPLES):
            chunk = samples[i : i + CHUNK_SAMPLES]
            await ws.send(chunk.astype("<i2").tobytes())
            await asyncio.sleep(len(chunk) / 16000.0)
        speech_end = time.perf_counter()
        await ws.send("flush")
        try:
            await asyncio.wait_for(receiver, timeout=6.0)
        except asyncio.TimeoutError:
            pass
    return {
        "name": name,
        "partials": partials,
        "finals": finals,
        "final_text": finals[-1] if finals else "",
        "connect_s": round(t_connected - t_start, 3),
        "speech_s": round(speech_end - t_connected, 3),
        "finalize_s": round((events[-1]["t"] - speech_end) if events else -1, 3),
        "events": events,
    }


async def _collect(ws, partials, finals, events) -> None:
    while True:
        try:
            raw = await ws.recv()
        except websockets.ConnectionClosed:
            return  # flush 后服务端正常结束连接
        if isinstance(raw, bytes):
            continue
        data = json.loads(raw)
        if data.get("type") == "partial":
            partials.append(data.get("text", ""))
        elif data.get("type") == "final":
            finals.append(data.get("text", ""))
        events.append({"t": time.perf_counter(), "type": data.get("type")})
        if data.get("type") == "final":
            # final 后服务端保持连接；等待一小会看是否有后续 final，然后结束。
            await asyncio.sleep(1.0)


async def main() -> int:
    files = sorted(AUDIO_DIR.glob("*.wav"))
    print(f"injecting {len(files)} command wavs into {WS_URL}")
    ok = 0
    total = 0
    latencies: list[float] = []
    rows = []
    for wav in files:
        name = wav.stem
        expect = EXPECT.get(name)
        result = await inject_one(name, wav)
        final_text = result["final_text"]
        recognized = bool(final_text.strip())
        matched = recognized and expect is not None and expect in final_text
        if expect is None:
            # 负向对照只记录
            verdict = "recorded"
        elif matched:
            verdict = "MATCH"
            ok += 1
            latencies.append(result["finalize_s"])
        else:
            verdict = "MISS"
        if expect is not None:
            total += 1
        rows.append((name, verdict, recognized, final_text, result))
        print(
            f"[{verdict:>8}] {name}: final={final_text!r} partials={len(result['partials'])} "
            f"speech={result['speech_s']}s finalize={result['finalize_s']}s"
        )
    if latencies:
        lat = sorted(latencies)
        p50 = lat[len(lat) // 2]
        p95 = lat[int(len(lat) * 0.95) - 1 if len(lat) > 1 else 0]
        print(f"\naccuracy (keyword match): {ok}/{total}")
        print(f"finalize latency after speech end: P50={p50:.2f}s P95={p95:.2f}s  min={lat[0]:.2f}s max={lat[-1]:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
