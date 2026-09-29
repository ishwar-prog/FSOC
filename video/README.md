# COSTA videos

Videos for COSTA, the Coarse Optical Tracking & Alignment System.

Remotion 4 project, same setup as H.A.L.O.'s. All compositions are 1920×1080 at 30 fps.

```bash
npm install
npm run dev                                   # Remotion Studio
npx remotion render Intro ../docs/assets/intro.mp4 --codec=h264 --crf=18
npx remotion render Launch ../docs/assets/launch.mp4 --codec=h264 --crf=17
npx remotion still Banner ../docs/assets/banner-light.png   # also Features, Terminals, Architecture
```

| Composition | Length | What it is |
|---|---|---|
| `Launch` | 10 s | A naive tracker grabs the brightest light; the real one is found by its 5 Hz blink and locked |
| `Demo` | ~17 s | Real app recording, LEO pass: cold start, lock, blockage, re-acquisition, 6/6 targets |
| `Intro` | ~41 s | Link → mark → sky → blink → lock → terminals → hazards → benchmark → close |
| `Banner`, `Features`, `Terminals`, `Architecture` | stills | README images |

| Path | What it is |
|---|---|
| `src/Intro.tsx` | Scene order, durations and sound cues (the only place to retime the intro) |
| `src/scenes.tsx` | One component per intro scene |
| `src/launch/Launch.tsx` | The launch cut |
| `src/demo/Demo.tsx` | Demo cut: segments, zooms and captions over `public/demo/raw.mp4` |
| `src/fsoc.tsx` | Sky of lights with real blink models, lock brackets, traces, state pills, the mark |
| `src/components.tsx` | Motion toolkit shared with H.A.L.O. |
| `src/theme.ts` | Palette from `ui/theme.py`, fonts, benchmark numbers (seed 42) |
| `public/data/` | Real tracker output from `python tools/export_video_data.py` |

The lock scene replays the real *Drone · Hover Hold* run frame by frame (acquisition 1.03 s).
Rerun `tools/export_video_data.py` when the tracker changes, then re-render.

WebP for the README:

```bash
ffmpeg -i docs/assets/intro.mp4 -vf "fps=12,scale=960:-1:flags=lanczos" -c:v libwebp -quality 55 -loop 0 docs/assets/intro.webp
```

## Demo footage

`public/demo/raw.mp4` is not committed. Regenerate it from the repository root (needs the app's
Python dependencies and ffmpeg), then render `Demo`:

```bash
python tools/record_demo.py video/public/demo/raw.mp4
```

The recorder scripts the scenario through the engine and grabs the app window's own pixels, so
nothing else on the screen is captured. Grabbing is slower than real time, so the clip plays at
about 2.4× the app's clock.
