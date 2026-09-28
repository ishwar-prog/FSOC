# FSOC Beacon Tracker videos

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
| `Intro` | ~41 s | Link → mark → sky → blink → lock → terminals → hazards → benchmark → close |
| `Banner`, `Features`, `Terminals`, `Architecture` | stills | README images |

| Path | What it is |
|---|---|
| `src/Intro.tsx` | Scene order, durations and sound cues (the only place to retime the intro) |
| `src/scenes.tsx` | One component per intro scene |
| `src/launch/Launch.tsx` | The launch cut |
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
