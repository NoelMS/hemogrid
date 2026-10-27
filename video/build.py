"""Explainer video build.  Usage (from the repo root, after video/narration.py):
    python video/build.py scene            # extract the live ER diagram, write work/scene.html
    python video/build.py stills 3 20 ...  # PNG stills at given seconds into work/stills (for review)
    python video/build.py frames           # capture every frame (parallel headless Edge)
    python video/build.py audio            # narration + music + soft effects -> work/mix.wav
    python video/build.py mux              # encode app/static/explainer.mp4, poster and captions
"""
import json, math, multiprocessing as mp, pathlib, re, subprocess, sys, wave
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = HERE / "work"
FPS, W, H = 30, 1920, 1080
TL = json.loads((WORK / "timeline.json").read_text(encoding="utf-8")) if (WORK / "timeline.json").exists() else None
FFMPEG = r"N:\Tools\ffmpeg\bin\ffmpeg.exe"


def nums():
    ms = [float(x) for x in re.findall(r"([\d.]+) ms", (ROOT / "docs" / "indexing_demo.txt").read_text(encoding="utf-8"))]
    keys = ["Q1a", "Q1b", "Q2a", "Q2b", "Q2c", "Q3a", "Q3b", "Q3c"]
    assert len(ms) == len(keys), ms
    return dict(zip(keys, ms))


def build_scene():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        pg.goto("http://127.0.0.1:5057/design/er", wait_until="domcontentloaded")
        pg.wait_for_selector("pre.mermaid svg")
        pg.wait_for_timeout(500)
        svg = pg.evaluate("document.querySelector('pre.mermaid svg').outerHTML")
        b.close()
    svg = re.sub(r'\sstyle="max-width:[^"]*"', "", svg, count=1)
    html = (HERE / "scene.tpl.html").read_text(encoding="utf-8")
    html = html.replace("<!--__ER_SVG__-->", svg).replace("/*__TIMELINE__*/", json.dumps(TL)).replace("/*__NUMS__*/", json.dumps(nums()))
    (WORK / "scene.html").write_text(html, encoding="utf-8")
    print("scene.html written", len(html))


def shoot(args):
    times, outdir, fmt = args
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.goto((WORK / "scene.html").as_uri(), wait_until="domcontentloaded")
        pg.wait_for_function("window.__ready === true", timeout=30000)
        pg.wait_for_timeout(300)
        for name, t in times:
            pg.evaluate(f"__render({t})")
            kw = {"type": "jpeg", "quality": 92} if fmt == "jpg" else {"type": "png"}
            pg.screenshot(path=str(outdir / f"{name}.{fmt}"), **kw)
        b.close()
    return len(times)


def stills(ts):
    out = WORK / "stills"
    out.mkdir(exist_ok=True)
    shoot(([(f"t{t:06.2f}", t) for t in ts], out, "png"))
    print("stills in", out)


def frames(workers=4):
    out = WORK / "frames"
    out.mkdir(exist_ok=True)
    n = int(TL["total"] * FPS) + 1
    todo = [(f"f{i:05d}", i / FPS) for i in range(n) if not (out / f"f{i:05d}.jpg").exists()]
    chunks = [todo[i::workers] for i in range(workers)]
    print(f"{len(todo)} of {n} frames to capture")
    with mp.Pool(workers) as pool:
        print(sum(pool.map(shoot, [(c, out, "jpg") for c in chunks if c])), "captured")


SR = 44100


def load_wav(path):
    with wave.open(str(path)) as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype=np.int16 if sw == 2 else np.uint8).astype(np.float32)
    a = a.reshape(-1, ch).mean(axis=1) / (32768.0 if sw == 2 else 128.0)
    return np.interp(np.arange(0, len(a), sr / SR), np.arange(len(a)), a).astype(np.float32)


def smooth(x, n):
    """Centered moving average via cumulative sum (O(len) instead of np.convolve's O(len * n))."""
    c = np.cumsum(np.insert(x.astype(np.float64), 0, 0.0))
    half = n // 2
    i = np.arange(len(x))
    lo, hi = np.clip(i - half, 0, len(x)), np.clip(i + half + 1, 0, len(x))
    return ((c[hi] - c[lo]) / (hi - lo)).astype(np.float32)


def audio():
    total = TL["total"] + 1.5
    n = int(total * SR)
    t = np.arange(n) / SR
    # --- narration
    voice = np.zeros(n, np.float32)
    for sc in TL["scenes"]:
        a = load_wav(WORK / "audio" / f"{sc['id']}.wav")
        i = int(sc["narr_start"] * SR)
        voice[i:i + len(a)] += a[: n - i]
    voice *= 0.9 / max(np.abs(voice).max(), 1e-6)
    # --- music: A minor pad (Am F C G, 8 s each), soft attack, slow filter via smoothing, plus a quiet pluck arpeggio
    chords = [[110.0, 164.81, 220.0, 261.63], [87.31, 130.81, 174.61, 261.63], [130.81, 196.0, 261.63, 329.63], [98.0, 146.83, 196.0, 293.66]]
    pad = np.zeros(n, np.float32)
    seg = 8.0
    for k in range(int(math.ceil(total / seg))):
        s0, s1 = int(k * seg * SR), min(n, int((k + 1) * seg * SR))
        tt = np.arange(s1 - s0) / SR
        env = np.minimum(1, tt / 2.0) * np.minimum(1, (seg - tt) / 2.0)
        for f in chords[k % 4]:
            for det in (-0.4, 0.4):
                pad[s0:s1] += (np.sin(2 * np.pi * (f + det) * tt) + 0.3 * np.sin(4 * np.pi * f * tt)) * env * 0.05
    plucks = np.zeros(n, np.float32)
    scale = [220.0, 261.63, 329.63, 392.0, 440.0, 523.25]
    step = 0.75
    for j in range(int(total / step)):
        f = scale[(j * 5 + j // 6) % len(scale)]
        i = int(j * step * SR)
        d = int(0.9 * SR)
        tt = np.arange(min(d, n - i)) / SR
        plucks[i:i + len(tt)] += np.sin(2 * np.pi * f * tt) * np.exp(-tt * 5.5) * 0.028
    music = pad + plucks
    # duck the music under speech
    speech = smooth(np.abs(voice), int(0.25 * SR))
    duck = 1 - 0.45 * np.clip(speech / 0.08, 0, 1)
    duck = smooth(duck, int(0.3 * SR))
    music *= duck
    # --- soft marker at every scene start: A5 + E6 bell, low in the mix
    fx = np.zeros(n, np.float32)
    for sc in TL["scenes"]:
        i = int((sc["start"] + 0.05) * SR)
        tt = np.arange(min(int(1.4 * SR), n - i)) / SR
        fx[i:i + len(tt)] += (np.sin(2 * np.pi * 880 * tt) + 0.5 * np.sin(2 * np.pi * 1318.5 * tt)) * np.exp(-tt * 3.2) * 0.035
    mix = voice + music + fx
    fade = np.minimum(1, t / 1.0) * np.minimum(1, (total - t) / 2.0)
    mix = mix * fade
    mix *= 0.89 / np.abs(mix).max()
    pcm = (mix * 32767).astype(np.int16)
    with wave.open(str(WORK / "mix.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    print("mix.wav", round(total, 1), "s")


def vtt():
    def ts(x):
        return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{x % 60:06.3f}"
    out = ["WEBVTT", ""]
    for sc in TL["scenes"]:
        ss = re.findall(r"[^.!?]+[.!?]+", sc["text"])
        total, cum = len("".join(ss)), 0
        for s in ss:
            a = sc["narr_start"] + sc["narr_dur"] * cum / total
            cum += len(s)
            b = sc["narr_start"] + sc["narr_dur"] * cum / total
            out += [f"{ts(a)} --> {ts(b)}", s.strip(), ""]
    (ROOT / "app" / "static" / "explainer.vtt").write_text("\n".join(out), encoding="utf-8")


def mux():
    fr = WORK / "frames"
    poster_src = fr / f"f{int(7.0 * FPS):05d}.jpg"
    (ROOT / "app" / "static" / "explainer.jpg").write_bytes(poster_src.read_bytes())
    (fr / "f00000.jpg").write_bytes(poster_src.read_bytes())           # poster baked in as frame 0 (replaces it, no extra frame)
    out = ROOT / "app" / "static" / "explainer.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(fr / "f%05d.jpg"), "-i", str(WORK / "mix.wav"),
                    "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-r", str(FPS),
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(out)], check=True)
    vtt()
    print(out, round(out.stat().st_size / 1e6, 1), "MB")


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"scene": build_scene, "frames": frames, "audio": audio, "mux": mux}.get(cmd, lambda: stills([float(x) for x in sys.argv[2:]]))()
