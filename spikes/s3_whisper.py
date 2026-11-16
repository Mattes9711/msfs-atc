"""Spike (step 3): push-to-talk recording + faster-whisper transcription, with timings."""
import argparse
import ctypes
import re
import time
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
RECORDINGS = Path(__file__).resolve().parent.parent / "recordings"
AVIATION_PROMPT = (
    "Clearance, ground, tower, departure, approach, runway, taxi, holding point, hold short, "
    "line up and wait, cleared for takeoff, cleared to land, flight level, squawk, QNH, "
    "information, niner, decimal, wilco, roger, going around. "
    "Alpha, Bravo, Charlie, Delta, Echo, Foxtrot, Golf, Hotel, India, Juliett, Kilo, Lima, Mike, "
    "November, Oscar, Papa, Quebec, Romeo, Sierra, Tango, Uniform, Victor, Whiskey, X-ray, Yankee, Zulu."
)


VK_CODES = {"right ctrl": 0xA3, "left ctrl": 0xA2, "right shift": 0xA1, "right alt": 0xA5, "caps lock": 0x14}


def key_down(vk):
    # The `keyboard` package's hook never fires on Python 3.14; polling the Win32 key state works system-wide
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def record_while_held(key, mic):
    import sounddevice as sd

    vk = VK_CODES[key]
    print(f"\nHold [{key}] and speak, release to stop.", flush=True)
    while not key_down(vk):
        time.sleep(0.01)
    print("  recording...", flush=True)
    chunks = []
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=mic,
                        callback=lambda data, frames, t, status: chunks.append(data.copy())):
        while key_down(vk):
            time.sleep(0.01)
    audio = np.concatenate(chunks).flatten() if chunks else np.zeros(0, dtype=np.float32)
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    print(f"  {audio.size / SAMPLE_RATE:.1f}s recorded, peak level {peak:.3f}"
          + ("  <- nearly silent, wrong mic? try --list-mics / --mic N" if peak < 0.02 else ""), flush=True)
    return audio


def save_wav(audio):
    RECORDINGS.mkdir(exist_ok=True)
    path = RECORDINGS / f"{len(list(RECORDINGS.glob('*.wav'))) + 1:03}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"  saved {path.name}", flush=True)


def load_wav(path):
    # faster-whisper's own file decoding breaks with PyAV 19, so decode 16-bit PCM ourselves
    with wave.open(str(path), "rb") as w:
        rate, channels = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = pcm.reshape(-1, channels).mean(axis=1).astype(np.float32) / 32768
    target_len = int(len(audio) * SAMPLE_RATE / rate)
    return np.interp(np.linspace(0, len(audio) - 1, target_len), np.arange(len(audio)), audio).astype(np.float32)


def load_model(name, device, compute_type):
    from faster_whisper import WhisperModel

    if compute_type is None:
        compute_type = "float16" if device == "cuda" else "int8"
    print(f"Loading {name} on {device}/{compute_type}...", flush=True)
    start = time.perf_counter()
    try:
        model = WhisperModel(name, device=device, compute_type=compute_type)
        # CUDA libraries are only loaded on the first transcription, so fail now rather than mid-flight
        list(model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language="en")[0])
    except Exception as e:
        if device == "cuda":
            raise SystemExit(f"CUDA failed: {e}\nctranslate2 needs cuBLAS 12 + cuDNN 9 DLLs; use --device cpu.")
        raise
    print(f"Ready in {time.perf_counter() - start:.1f}s", flush=True)
    return model


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def transcribe(model, audio, prompt, context, label=""):
    print("  transcribing...", flush=True)
    start = time.perf_counter()
    segments, info = model.transcribe(
        audio, language="en", beam_size=5, vad_filter=True, initial_prompt=prompt,
    )
    text = " ".join(s.text.strip() for s in segments)
    elapsed = time.perf_counter() - start
    echo = context and words(text) and words(text) <= words(context)
    print(f"{label}[{info.duration:.1f}s audio -> {elapsed:.2f}s] {text!r}"
          + ("  <- only words from --context, probably an echo" if echo else ""), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="small.en")
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    p.add_argument("--compute-type", default=None)
    p.add_argument("--key", default="right ctrl", choices=list(VK_CODES))
    p.add_argument("--file", type=Path, help="transcribe a wav file (or every wav in a folder) instead of the mic")
    p.add_argument("--no-prompt", action="store_true", help="disable the aviation initial_prompt")
    p.add_argument("--context", default="", help='expected names, e.g. "Hamburg Ground, Lufthansa 4AB, DLH4AB"')
    p.add_argument("--mic", type=int, help="input device index from --list-mics")
    p.add_argument("--list-mics", action="store_true")
    args = p.parse_args()

    import sounddevice as sd

    if args.list_mics:
        default_in = sd.default.device[0]
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and d["hostapi"] == 0:
                print(("* " if i == default_in else "  ") + f"{i:3} {d['name']}")
        return

    prompt = None if args.no_prompt else f"{args.context} {AVIATION_PROMPT}".strip()
    model = load_model(args.model, args.device, args.compute_type)
    if not args.file:
        mic = args.mic if args.mic is not None else sd.default.device[0]
        print(f"Microphone: [{mic}] {sd.query_devices(mic)['name']}", flush=True)
    if args.file:
        files = sorted(args.file.glob("*.wav")) if args.file.is_dir() else [args.file]
        for f in files:
            transcribe(model, load_wav(f), prompt, args.context, label=f"{f.name} ")
        return
    print("Ctrl+C to stop. Recordings are saved to recordings/.")
    try:
        while True:
            audio = record_while_held(args.key, mic)
            if audio.size:
                save_wav(audio)
                transcribe(model, audio, prompt, args.context)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
