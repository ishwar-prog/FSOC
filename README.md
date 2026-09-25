# FSOC Beacon Tracker — Coarse PAT System (SIH 2026 · PS SIH26169)

*AI-Based Virtual Camera Tracking System for Coarse Alignment of Mobile FSOC Terminals*

A closed-loop pointing, acquisition and tracking (PAT) system for a free-space optical link. The system:

1. Detects every point light in a narrow-field NIR camera.
2. **Recognises which of them is the partner terminal's beacon** from its learned blink signature, not its brightness.
3. Tracks it in line-of-sight angles and drives a pan/tilt gimbal to keep it on bore-sight.

The remote terminal can be a drone, an aircraft, a ship, a LEO satellite, a GEO relay or a space station. It moves realistically and can be steered by hand. Everything is scored live against the SIH reference numbers. The same tracking core runs on simulation today, and on recorded video and real camera + gimbal hardware next.

---

## 1. Quick start

| What | How |
|---|---|
| Run the application (no Python needed) | `dist\FSOC_Beacon_Tracker.exe` |
| Run from source | `python -m pip install -r requirements.txt` then `python main.py` |
| Headless validation of every terminal, pattern and hazard | `python benchmark.py` (add `--duration 20` for a quick pass, `--only leo,decoys` to filter) |
| Make realistic test footage for video mode | `python tools/make_demo_video.py` → `demo_videos\` (clips + ground-truth CSVs) |
| Rebuild the .exe | `powershell -ExecutionPolicy Bypass -File build_exe.ps1` |

Logs (per-frame CSV + JSON summary) and a saved beacon signature are written to a `logs\` folder next to the executable.

---

## 2. What is new in this version

| Request | What was built |
|---|---|
| The beacon is not always the brightest light | **Learned beacon identification** (section 5). Every light gets a tracklet and a brightness history; its blink rhythm is Fourier-analysed. The tracker learns the real beacon's signature while locked and rejects look-alikes: stars, street and tower lights, strobes, glints, other satellites, even a second laser link blinking at a different rate. Nothing about the beacon is hard-coded. |
| Satellite and space station | **LEO pass** (circular orbit over a spherical Earth, rise → culmination → set), **GEO relay** (36 000 km, fixed in a drifting star field) and **ISS pass** (420 km, bright sun-lit body next to the beacon). Acquisition follows the NASA OPALS procedure: open-loop pre-pointing from the predicted orbit, then closed-loop tracking of the beacon. |
| Movable, variable terminals | Remote B: live speed, distance, direction, altitude and a *real-world variation* slider (gusts, course wander, attitude wobble). Manual Drive: drag Terminal B in the world view and it flies/sails there at platform-limited speed. Satellites: orbit altitude, highest point, pass direction, time speed. Ground A: fixed, vehicle or ship-deck mount, position and mast height (drag it too), gimbal slew limit. Every change blends in smoothly. |
| Bigger, adjustable screens | Three resizable panes (default 20 % / 60 % / 20 %). Camera and world views share the centre and can be resized or expanded to fill it. |
| Easier sidebar and info buttons | Sidebar split into **Remote B · Ground A · Environment**. Every section and every technical readout has an **(i)** button that explains it in plain words on hover. |
| Remove the System & inputs page | Removed. The app has **Live tracking** and **Analytics**. |
| Dark mode | One-click light/dark theme; layout and settings are kept when switching. |
| Watch the validation suite actually run, and stop it | The suite's card now shows a **live camera preview** of whichever case is running — which case, its elapsed time and state — updated as it goes, plus a **Stop** button that aborts immediately, even mid-case, and marks the interrupted row STOPPED rather than pass/fail. |
| Show the camera's view angle, not a laser beam | The link between the terminals is now drawn as the camera's real field of view — a wedge that widens with range and tints to the tracker's state colour when locked — instead of a beam line, in both the ground/sea perspective and the space schematic. |
| A second satellite, for two-satellite links | Ground A can itself be **a satellite** (`Mount → Satellite`): its own LEO orbit, altitude/inclination/heading sliders, a satellite icon and label in the world view. Pair it with a LEO/GEO/ISS pattern on Remote B for a genuine satellite-to-satellite crosslink — both ends moving, both needing to find and hold the other's beacon. |
| Make it work on video | **Environment → Input source → Load video…** swaps the simulator for a real recorded clip; the identical detector, identifier, Kalman tracker and gimbal controller run on it unchanged, and **all six mission targets are scored** (section 6). Click any light in the camera view to pick the target by hand. **Back to simulation** returns to the simulator. |

---

## 3. SIH reference numbers — definitions used

Ground truth is used **only by the evaluator**. The detector, identifier, tracker and controller never see it.

| Metric | Target | Exactly what is measured |
|---|---|---|
| Acquisition time | ≤ 2 s | Cold start (gimbal parked / pre-pointed, no track) → first confirmed LOCK |
| Tracking error | ≤ 10 px | Mean distance between the detected centroid and the true beacon centre on the sensor, over LOCKED frames |
| Target loss | < 5 % | Frames after first lock without a valid lock. Valid = LOCKED or COASTING, **and** the track within 40 px of the true line of sight. A lock on a decoy or star counts as a loss. |
| Re-acquisition | ≤ 1 s | Loss of valid lock → LOCKED again, counted from when the beacon is physically visible again. The **worst case** is scored. |
| Processing speed | ≥ 20 FPS | Achieved end-to-end vision pipeline rate; capacity is also shown |
| Camera update rate | ≥ 30 Hz render / ≥ 20 Hz control | GUI render loop and gimbal control loop, on separate threads |

The **Mission targets** panel shows all six live with PASS/FAIL. **Cold restart** measures acquisition; **Block beacon 2.5 s** (longer than the 1.5 s coast window) measures re-acquisition.

### Validation results

`python benchmark.py`: 40 s deterministic cold-start runs, seed 42. Each case includes an injected 2.4 s beacon blockage, so re-acquisition is exercised everywhere.

**All 28 cases pass all six targets with seed 42.** Capacity below was measured while two suites ran at the same time on a 4-thread i3.

| Case | Acquisition | Tracking error | Target loss | Worst re-acq | Result |
|---|---|---|---|---|---|
| Drone · Hover Hold | 1.03 s | 0.02 px | 2.91 % | 0.17 s | PASS |
| Aircraft · Linear Flyby | 1.23 s | 0.03 px | 2.92 % | 0.17 s | PASS |
| Aircraft · Circular Orbit | 1.23 s | 0.04 px | 2.92 % | 0.17 s | PASS |
| Aircraft · Figure-Eight | 1.20 s | 0.03 px | 2.92 % | 0.17 s | PASS |
| Drone · Zig-Zag Evasive | 1.03 s | 0.03 px | 2.91 % | 0.17 s | PASS |
| Drone · Spiral Approach | 1.03 s | 0.04 px | 2.91 % | 0.17 s | PASS |
| Ship · Maritime Sway | 1.20 s | 0.03 px | 2.92 % | 0.17 s | PASS |
| Ship · Transit | 0.83 s | 0.03 px | 2.89 % | 0.17 s | PASS |
| Drone · Random Manoeuvre | 1.03 s | 0.03 px | 2.91 % | 0.17 s | PASS |
| Satellite · LEO Pass | 1.20 s | 0.02 px | 3.35 % | 0.33 s | PASS |
| Satellite · GEO Relay | 1.20 s | 0.03 px | 4.98 % | 0.97 s | PASS |
| Space station · ISS Pass | 1.20 s | 0.02 px | 3.35 % | 0.33 s | PASS |
| Fog 80 % | 1.23 s | 0.09 px | 3.01 % | 0.20 s | PASS |
| Rain 80 % | 1.23 s | 0.05 px | 2.92 % | 0.17 s | PASS |
| Heat Shimmer 80 % | 1.20 s | 3.28 px | 2.92 % | 0.17 s | PASS |
| Sensor Noise 80 % | 1.03 s | 0.09 px | 2.91 % | 0.17 s | PASS |
| Mount Vibration 80 % | 1.23 s | 0.03 px | 3.44 % | 0.37 s | PASS |
| Sun Glare 80 % | 1.23 s | 0.04 px | 2.92 % | 0.17 s | PASS |
| Occlusion 80 % | 1.03 s | 0.03 px | 4.53 % | 0.13 s | PASS |
| Decoy Lights 80 % | 1.23 s | 0.04 px | 2.92 % | 0.17 s | PASS |
| Dim beacon · bright blinking decoys | 1.03 s | 0.04 px | 2.91 % | 0.17 s | PASS |
| Night · Decoys + Noise | 1.43 s | 0.07 px | 3.37 % | 0.33 s | PASS |
| LEO pass · dense satellites + shimmer | 1.20 s | 2.04 px | 3.35 % | 0.33 s | PASS |
| ISS pass at dusk · sun-lit body | 1.10 s | 0.03 px | 3.08 % | 0.27 s | PASS |
| Vehicle-mounted terminal A | 1.20 s | 0.03 px | 2.92 % | 0.17 s | PASS |
| Ship-to-ship · deck mount | 0.83 s | 1.64 px | 2.89 % | 0.17 s | PASS |
| Fast aircraft · 2× speed | 1.40 s | 0.04 px | 2.93 % | 0.17 s | PASS |
| Storm (fog+rain+shimmer+vibration+occlusion) | 1.60 s | 2.19 px | 3.04 % | 0.20 s | PASS |

About 2.4 % of every loss figure comes from the injected blockage. Acquisition is ~1 s (not ~0.3 s as in the previous version) because a lock now also waits for evidence that the light is really the beacon.

**Known limits (seed 7):** 25 of 28 cases pass. Three fail:

- **Mount Vibration** — target loss 11.8 %, re-acquisition 3.1 s: vibration smear can briefly take the lock.
- **Night · Decoys + Noise** — the lock can be taken by a decoy after the blockage.
- **ISS pass at dusk** — acquisition 2.9 s.

The live panel reports such cases honestly as FAIL.

---

## 4. Remote terminals and patterns

All motion is a smooth analytic function of time with platform-realistic speeds and accelerations. Switching pattern cross-blends over 5 s; speed changes ramp; nothing jumps.

| Terminal | Patterns | Notes |
|---|---|---|
| Drone | Hover Hold · Zig-Zag Evasive · Spiral Approach · Random Manoeuvre · Manual Drive | Hovers, ~1 g weaving, 3 km ↔ 0.9 km range change |
| Aircraft | Linear Flyby · Circular Orbit · Figure-Eight · Manual Drive | Cannot hover; loiters around a manual waypoint |
| Ship | Maritime Sway · Ship Transit · Manual Drive | Mast-top beacon, roll and pitch in a sea state |
| Satellite | LEO Pass · GEO Relay | Ephemeris-cued (σ 0.5°); pass geometry gives the real 0.1–1 °/s LOS rates |
| Space station | ISS Pass | Fast, bright sun-lit body beside the beacon (hardest at dusk) |

Ground terminal A: fixed pier, vehicle (road motion + residual jitter after INS stabilisation), ship deck, or **satellite** — its own LEO orbit (altitude / inclination / heading), for a satellite-to-satellite crosslink when paired with a LEO/GEO/ISS pattern on Remote B.

## 5. Beacon identification — how it works

A beacon cannot be found by brightness alone: at range it can be fainter than a street light, a star or a sun-lit spacecraft. Operational links therefore key (modulate) the beacon and confirm it with geometry. This system does the same, and **learns** the signature instead of being told it.

1. **Tracklets.** Every detected light is associated frame-to-frame in line-of-sight angles. Gimbal motion is compensated, so stars, lamps and satellites all form clean tracks.
2. **Forced photometry.** Each frame, brightness is measured at every tracklet's position, including frames where the detector did not fire. An OFF phase is recorded as *dark*, not *missing*.
3. **Features.** The history is resampled, detrended and Fourier-analysed: dominant frequency, periodicity (power in the peak), modulation depth and duty cycle.
4. **Naive-Bayes likelihood ratio: beacon vs clutter.**
   - Before anything is learned, only generic knowledge is used: a beacon is keyed with a roughly symmetric on/off pattern, faster than natural flicker, tower lights or tumbling glints.
   - While locked on a light that *does* look keyed, the beacon model learns its real frequency, depth and duty cycle, and the clutter model learns everything else in view.
   - A steady star is never learned as "the beacon".
5. **Fusion with geometry.**
   - Acquisition needs cue consistency (GPS telemetry or ephemeris), rate consistency *and* identity.
   - While locked, another light cannot take over just by passing close. If the locked light proves unkeyed while a clearly beacon-like light sits in the cue cone, the lock is handed over.
6. **Portable.** *Save signature* writes it to JSON; a video or hardware session can load it and start already knowing its beacon. *Relearn* forgets it (for a different beacon).

The **Beacon identity** card shows the learned rate/duty, the probability that the locked light is the beacon, and a bar for every light in view.

## 5b. Video input — real footage, all six targets

Simulation is where the system is *tuned*; a real recording is where it has to hold up. Video mode
runs the **same** detector, identifier, Kalman tracker and controller — nothing is swapped for a
different algorithm, and no model is trained. Load a clip from **Environment → Input source →
Load video…**.

**What real footage needed that simulation did not**

| Problem on real video | Fix |
|---|---|
| The whole vision chain kept the simulator's 640×480 intrinsics while frames were 1280×720, so every pixel↔angle conversion, ROI and on-screen overlay was at the wrong scale — the lock brackets were drawn far from the beacon and it looked like nothing was tracked. | The pipeline, evaluator and camera view are rebuilt around the video's own intrinsics on load, and every overlay is scaled to the actual frame. |
| An uncalibrated clip gives no way to know its true field of view, and several gates are specified in degrees. | Default to the angular scale those gates were tuned at (160 px/°), overridable when the real optics are known. |
| No telemetry cue exists, so selection falls back toward "brightest wins" — and a target that does not blink cannot be told from a street lamp by its signature. | Sources are also scored on **how differently they move from the rest of the field** — a terminal drifting across fixed lights, or a fixed one against drifting stars. Only used when there is no cue, so simulator behaviour is untouched. |
| Some targets are genuinely ambiguous: a steady beacon beside a blinking decoy is, to any automatic rule, the *less* beacon-like of the two. | **Click the target in the camera view.** The seed waits for a solid detection (an operator often clicks while a keyed beacon is dark), follows the target while it waits, and then owns the lock — identity evidence alone cannot hand it to a look-alike. |

**Measured, against known truth.** `tools/make_demo_video.py` renders realistic clips — 1280×720
H.264, wide field of view, textured day/night scenes, handheld shake, auto-exposure drift, lens
flare, birds, street lights and a rival blinker — each with a `_truth.csv` of the real beacon
position, so the tracker can be scored honestly rather than eyeballed.

| Clip | Acquisition | Tracking error | Target loss | Re-acq | On target vs truth |
|---|---|---|---|---|---|
| Day · drone, 5 Hz beacon | 0.79 s | 0.93 px | 0.00 % | — | 100.0 % |
| Day · sun glare + lens flare | 0.80 s | 1.06 px | 0.00 % | — | 100.0 % |
| Night · city lights + rival blinker | 0.76 s | 0.96 px | 0.00 % | — | 100.0 % |
| Steady (non-blinking) beacon ¹ | 0.76 s | 1.15 px | 0.30 % | 0.03 s | 97.3 % |
| Tiny, far, 8 Hz beacon | 0.76 s | 1.12 px | 0.00 % | — | 100.0 % |

Targets: acquisition ≤ 2 s · tracking error ≤ 10 px · target loss < 5 % · re-acquisition ≤ 1 s ·
≥ 20 FPS · ≥ 30/20 Hz. Every clip meets all six.

¹ Click-seeded: a steady target next to a blinking decoy is ambiguous by design, since the whole
premise of automatic identification is that beacons are keyed. One click resolves it.

*"On target vs truth" is the share of frames where the track sits within 40 px of the true beacon
position from the sidecar file — an independent check, not one of the six targets.*

**Real recordings (1280×720, 24 FPS, with burned-in HUD text, a watermark, star-field
brightness bursts, crack overlays, glitch bands and smoke).** On these the simulator-tuned front
end failed outright — the beacon was ~40 px wide, the point-source top-hat hollowed it into a
ring, and the tracker locked HUD digits instead. Three general mechanisms fixed it:

- **Scale-space detection** — the same detector also runs on a ½ and ¼ image pyramid, so a
  40 px beacon is found as cleanly as a 2 px one.
- **Size-aware photometry** — each light's brightness is measured over an aperture matched to
  its size, so the blink identifier sees large beacons correctly.
- **Scene-relative saliency** (no-cue mode only) — every light is ranked on prominence vs the
  field, blink evidence, motion distinctiveness and persistence, with a penalty for static
  lights in the frame's border band (timestamps, OSD text, logos, watermarks). The lock is
  continuously re-checked and handed to a clearly better-ranked light if the first pick was wrong.

| Clip | On true beacon ² | Acquisition | Tracking error | Target loss | All six KPIs |
|---|---|---|---|---|---|
| Bright beacon + star-field burst (1) | 100.0 % | 0.35 s | 0.24 px | 0.00 % | pass |
| Bright beacon + star-field burst (2) | 94.0 % | 0.35 s | 1.25 px | 0.00 % | pass |
| Three dots + crack overlays (1) | 99.3 % | 0.33 s | 0.39 px | 0.00 % | pass |
| Three dots + crack overlays (2) | 95.8 % | 0.33 s | 1.00 px | 0.00 % | pass |
| Smoke + cracks + fast pan | 15.6 % | 0.35 s | 0.16 px | 0.00 % | pass — **but wrong light** |

² Share of frames within 40 px of the beacon position labelled offline from the whole clip
(most prominent light that is not a static border overlay). This independent check matters:
the six KPIs are self-measured on video and **cannot tell a correct lock from a wrong one** —
the last clip passes all six while holding the wrong light.

**Known limits (prototype).** The smoke/pan clip is not solved: the whole scene sweeps
~24 px/frame and the three dots are near-identical in brightness. Camera ego-motion estimation
(`EgoMotion` in `fsoc/core/video.py`) measures that pan correctly but was destabilised by glitch
frames on the other clips, so it is implemented but off (`Engine.VIDEO_EGO_MOTION`). Click-to-seed
remains available for ambiguous footage.

**How the six targets are scored without ground truth.** A real recording has no known beacon
position, so three of them are re-derived from what a real terminal can observe about itself, and
the UI says so:

- **Tracking error** — residual between the detection and where the filter predicted it would be.
  This is the classical tracking residual a real system reports; on the simulator it tracks the
  true error closely, so it is a fair stand-in.
- **Target loss** — share of frames after first lock with no live lock. The tracker's own state;
  needs no truth at all.
- **Re-acquisition** — time from losing that lock to holding a confirmed one again.
- Acquisition, processing speed and camera update rate are measured exactly as in simulation.

**Why not YOLO.** A beacon is not a semantic object class — it is a photometric and temporal
phenomenon, a few pixels across, defined by *how it blinks and moves*. A COCO-trained detector has
no "beacon" class, and training one would need labelled footage that does not exist here, while
adding a deep-learning runtime to a 107 MB executable. Motion segmentation (MOG2) was implemented
and measured: it made things **worse** (57–77 % loss on the day clip), because it offers spurious
movers exactly during the beacon's dark half. It is kept in `fsoc/core/video.py`, off by default,
for footage where the target is genuinely not a bright source.

---

## 6. Hazards (8, freely combinable, intensity 0–100 %, fade in smoothly)

| Hazard | Physical model |
|---|---|
| Fog | Koschmieder visibility 30 → 2 km; transmission, path-radiance veil, contrast loss, forward-scatter halo |
| Rain | Rain extinction, motion-blurred streaks, refractive droplets on the window |
| Heat Shimmer | Log-normal scintillation, angle-of-arrival wander (Ornstein–Uhlenbeck), beam blur |
| Sensor Noise | Shot + read noise, row banding, hot and flickering pixels |
| Mount Vibration | 2–21 Hz multi-tone LOS jitter up to ±0.11°, with exposure smear |
| Sun Glare | Veiling glare near the sun and lens ghosts; the sun disk can enter the FOV |
| Occlusion | Birds, branches and clouds blocking the beacon (0.25–1.5 s events) |
| Decoy Lights | Ground/sea: steady street lights, 0.5 Hz tower lights, 1.6 Hz hazard lamps, glints, another laser beacon at a different rate, a crossing aircraft strobe. Space: denser field of satellites with tumbling glints on top of the sidereal-drifting star field and a planet. |

The camera is a 640×480 NIR (850 nm) sensor with a 4°×3° field of view. Time of day (Day / Dusk / Night) changes sky radiance, exposure and contrast; space scenes default to night.

---

## 7. Architecture

```
 FrameSource ─► BeaconDetector ─► BeaconIdentifier ─► LOS Kalman tracker ─► Acquisition FSM ─► pointing reference
 (sim / video /  top-hat, matched   tracklets, forced     Singer model,        SEARCH → ACQUIRING →       │
  live camera)   filter, CFAR,      photometry, FFT       adaptive noise,      LOCKED ⇄ COASTING →        ▼
                 shape tests        signature, learning   Mahalanobis gating   REACQUIRE           GimbalController ─► GimbalInterface
                                                                                                    FF + PI, 60 Hz      (sim / serial)
 Vision thread 30 Hz ───────────────────────────────────────────────────────────┘   Control thread 60 Hz ──┘
 GUI thread 60 Hz reads immutable snapshots (never blocks either loop)
```

| Package | Role |
|---|---|
| `fsoc/core` | Source-agnostic algorithms: detector, identifier, tracker, pipeline, controller. Never sees ground truth. |
| `fsoc/io` | `Frame`, `FrameSource` (`VideoFileSource`, `LiveCameraSource`), `GimbalInterface` (`SimulatedGimbal`, `StaticMount`, `SerialPanTiltGimbal`) |
| `fsoc/sim` | NIR sensor renderer, terminals (aerial, sea, orbital), star catalogue and space clutter, hazards, cue |
| `fsoc/runtime` | Threaded engine, SIH evaluator, recorder, validation suite |
| `gui` | PySide6 interface (Live tracking · Analytics), light and dark themes |

### Why these algorithms

- **Detector** — white top-hat + Gaussian matched filter + MAD-based CFAR threshold, then connected components with moment elongation and ring-contrast tests. No training data; the threshold follows the real noise floor of any camera.
- **Identifier** — see section 5. Modulation is the property a partner terminal controls, so it is the most reliable discriminator against uncontrolled background lights.
- **Tracker** — Kalman filter in **line-of-sight angles** using a Singer manoeuvring-target model. It is independent of the camera's own motion, which carries over to a real gimbal. An innovation whiteness test separates manoeuvres from jitter.
- **Acquisition** — the standard FSOC PAT procedure:
  - Aircraft/ships: GPS telemetry cue, then an Archimedean spiral over the cue uncertainty.
  - Spacecraft: pre-point to the ephemeris prediction and stare while candidates mature (OPALS-style).
  - Multi-hypothesis confirmation fuses cue distance, rate consistency and beacon identity.
- **Re-acquisition** — searches the orbit/track prediction first, then the cue cone. In star fields the gate is kept to arc-minutes and needs a little more proof.
- **Controller** — velocity feed-forward from the Kalman rate + PI feedback, rate- and acceleration-limited, 60 Hz.

---

## 8. Adding video and hardware (next stages)

Only the frame source and the gimbal change; `TrackingPipeline` and `GimbalController` are reused as-is. **Video is already wired into the app**: Live tracking → Environment → Input source → *Load video…* runs the identical pipeline on a recorded `.mp4`/`.avi`/`.mov`/`.mkv`, live, in the GUI (see section 9); *Back to simulation* returns to the simulator. The snippet below is the same thing headless, and the pattern hardware follows too.

```python
from fsoc.core import TrackingPipeline, GimbalController, CameraIntrinsics
from fsoc.io import VideoFileSource, LiveCameraSource, StaticMount

src = VideoFileSource("benchmark.mp4", hfov_deg=4.0)        # or LiveCameraSource(0, my_gimbal)
pipe = TrackingPipeline(src.intrinsics)
pipe.cfg.require_cue = False                                 # no telemetry: search from bore-sight
pipe.identifier.load_signature("logs/beacon_signature.json") # optional: start already knowing the beacon
while (frame := src.read()) is not None:
    out = pipe.process_frame(frame)      # state, centroid, track, lights in view with beacon probability…
```

- **Hardware:** implement `GimbalInterface.read_state()` (encoder angles, timestamped) and `command_rate()` in `SerialPanTiltGimbal`. Run the same 60 Hz control tick as `Engine._control_tick`.
- **Timestamps:** frames must carry capture time and the encoder pose at mid-exposure. Tracker and identifier are timestamp-driven, so frame drops and variable FPS are handled.
- **Beacon rate:** keep the blink rate below half the camera frame rate (e.g. ≤ 12 Hz at 30 FPS) so it is not aliased.

---

## 9. Interface tour

- **Live tracking**
  - *Left rail* — **Remote B** (terminal type, movement, motion controls, beacon signal) · **Ground A** (mount — fixed / vehicle / ship / satellite, position or orbit, gimbal) · **Environment** (input source — simulation or a loaded video, time of day, hazards).
  - *Centre* — camera sensor (detections, identity labels, track brackets, ±10 px ring, scan path, sub-pixel zoom) with live readouts, and the world view:
    - aircraft/ships: 3-D scene — drag B to steer, drag A to move, drag space to orbit, scroll to zoom;
    - spacecraft: orbit schematic with pass progress and a sky plot.

    Drag the splitters to resize; ⤢ expands one view.
  - *Right rail* — the six mission targets, beacon identity, test buttons.
- **Analytics** — error timeline with state band, centroid bullseye, SNR / confidence / identity, loop rates vs thresholds, per-stage latency budget, session export and the in-app validation suite, with a live camera preview of whichever case is running and a Stop button.

## 10. Project layout

```
main.py                 entry point (PyInstaller target)
benchmark.py            headless validation CLI
build_exe.ps1           one-command build → dist\FSOC_Beacon_Tracker.exe
FSOC_Beacon_Tracker.spec
fsoc/core/              detector, identity, tracker, pipeline, controller, geometry
fsoc/io/                frame sources, gimbal interfaces
fsoc/sim/               world, terminals, patterns, sky, hazards, renderer
fsoc/runtime/           engine, evaluator, recorder, validation
ui/                     main_window, control_rail, camera_view, world_view, kpi_panel, charts,
                        analytics_page, info_text, theme (design system), widgets
assets/app.ico
assets/fonts/           Inter (Regular / Medium / SemiBold / Bold), bundled into the exe
_archive/alpha_v0.3_source.zip   previous alpha build (source)
```

The legacy alpha code (`simulation/` package and nine superseded `ui/*.py` files) is kept but not used by the application.
