# FSOC Beacon Tracker — Coarse PAT System (SIH 2026 · PS SIH26169)

*AI-Based Virtual Camera Tracking System for Coarse Alignment of Mobile FSOC Terminals*

A closed-loop pointing, acquisition and tracking (PAT) system for a free-space optical link. The system:

1. Detects the remote terminal's beacon in a narrow-field NIR camera.
2. Tracks it in line-of-sight angles.
3. Drives a pan/tilt gimbal to keep it on bore-sight.

It is scored live against every SIH reference number. The same tracking core is built to run on simulation today, and on recorded video and real camera + gimbal hardware next.

---

## 1. Quick start

| What | How |
|---|---|
| Run the application (no Python needed) | `dist\FSOC_Beacon_Tracker.exe` |
| Run from source | `python -m pip install -r requirements.txt` then `python main.py` |
| Headless validation of every pattern and hazard | `python benchmark.py` (add `--duration 20` for a quick pass) |
| Rebuild the .exe | `powershell -ExecutionPolicy Bypass -File build_exe.ps1` |

Logs (per-frame CSV + JSON summary) are written to a `logs\` folder next to the executable.

---

## 2. SIH reference numbers — definitions used

Ground truth is used **only by the evaluator**. The detector, tracker and controller never see it.

| Metric | Target | Exactly what is measured |
|---|---|---|
| Acquisition time | ≤ 2 s | Cold start (gimbal parked, no track) → first confirmed LOCK |
| Tracking error | ≤ 10 px | Mean distance between the detected centroid and the true beacon centre on the sensor, over LOCKED frames |
| Target loss | < 5 % | Frames after first lock without a valid lock. Valid = LOCKED or COASTING on the Kalman prediction, **and** the track within 40 px of the true line of sight. A lock on a decoy counts as a loss. |
| Re-acquisition | ≤ 1 s | Loss of valid lock → LOCKED again, counted from when the beacon is physically visible again. The **worst case** is scored. |
| Processing speed | ≥ 20 FPS | Achieved end-to-end vision pipeline rate (capture/render + detect + track); capacity is also shown |
| Camera update rate | ≥ 30 Hz render / ≥ 20 Hz control | GUI render loop and gimbal control loop, running on separate threads |

The **Mission targets** panel shows all six live with PASS/FAIL. Two buttons trigger the events being measured:

- **Cold restart** measures acquisition.
- **Block beacon 2.5 s** is longer than the 1.5 s coast window, so it measures re-acquisition.

### Validation results

`python benchmark.py`: 40 s deterministic cold-start runs, seed 42. Each case includes an injected 2.4 s beacon blockage, so re-acquisition is exercised everywhere.

**All 18 cases pass all six targets, with both seed 42 and seed 7.** Seed 42 results below; capacity was measured while two suites ran at the same time on a 4-thread i3.

| Case | Acquisition | Tracking error | Target loss | Worst re-acq | Result |
|---|---|---|---|---|---|
| Hover Hold | 0.33 s | 0.03 px | 2.52 % | 0.07 s | PASS |
| Linear Flyby | 0.43 s | 0.03 px | 2.52 % | 0.07 s | PASS |
| Circular Orbit | 0.37 s | 0.04 px | 2.52 % | 0.07 s | PASS |
| Figure-Eight | 0.37 s | 0.03 px | 2.52 % | 0.07 s | PASS |
| Zig-Zag Evasive | 0.33 s | 0.03 px | 2.52 % | 0.07 s | PASS |
| Spiral Approach | 0.33 s | 0.04 px | 2.52 % | 0.07 s | PASS |
| Maritime Sway | 0.43 s | 0.03 px | 2.52 % | 0.07 s | PASS |
| Random Manoeuvre | 0.33 s | 0.03 px | 2.52 % | 0.07 s | PASS |
| Fog 80 % | 0.37 s | 0.09 px | 2.60 % | 0.10 s | PASS |
| Rain 80 % | 0.43 s | 0.05 px | 2.52 % | 0.07 s | PASS |
| Heat Shimmer 80 % | 0.37 s | 3.27 px | 2.52 % | 0.07 s | PASS |
| Sensor Noise 80 % | 0.33 s | 0.09 px | 2.52 % | 0.07 s | PASS |
| Mount Vibration 80 % | 0.40 s | 0.03 px | 2.69 % | 0.13 s | PASS |
| Sun Glare 80 % | 0.43 s | 0.04 px | 2.52 % | 0.07 s | PASS |
| Occlusion 80 % | 0.33 s | 0.03 px | 4.03 % | 0.07 s | PASS |
| Decoy Lights 80 % | 0.37 s | 0.04 px | 2.52 % | 0.07 s | PASS |
| Night · Decoys + Noise | 0.67 s | 0.06 px | 2.79 % | 0.17 s | PASS |
| Storm (fog+rain+shimmer+vibration+occlusion) | 0.37 s | 2.17 px | 2.60 % | 0.10 s | PASS |

About 2.4 % of every loss figure comes from the injected 2.4 s blockage. The heat-shimmer error is real angle-of-arrival wander: the apparent spot moves away from the geometric centre.

Live GUI on the same laptop: vision 30 FPS, control ~60 Hz, render 48–62 Hz.

**Known limit:** stacking all 8 hazards at high intensity at night, then switching pattern during acquisition, can push acquisition past 2 s. The live panel reports this honestly as FAIL.

---

## 3. Beacon patterns (8)

All trajectories are smooth analytic functions of time, with platform-realistic speeds and accelerations. Switching pattern cross-blends over 5 s, so nothing ever jumps.

| Pattern | Platform | Behaviour |
|---|---|---|
| Hover Hold | Quadcopter | Station-keeping at 1.8 km with wind-gust drift |
| Linear Flyby | Fixed-wing | Racetrack: long straight passes and banked turns, 34 m/s |
| Circular Orbit | Fixed-wing | 380 m loiter orbit 2.1 km away |
| Figure-Eight | Fixed-wing | Lissajous surveillance pattern, changing range and bearing |
| Zig-Zag Evasive | Quadcopter | ~1 g lateral weaving with altitude bobbing |
| Spiral Approach | Quadcopter | Spirals in from 3 km to 0.9 km and back out (large brightness change) |
| Maritime Sway | Ship | Mast-top beacon at 2.6 km rolling and pitching in a sea state |
| Random Manoeuvre | Quadcopter | Seeded, smooth random manoeuvres |

## 4. Hazards (8, freely combinable, intensity 0–100 %, fade in over ~0.7 s)

| Hazard | Physical model |
|---|---|
| Fog | Koschmieder visibility 30 → 2 km; transmission, path-radiance veil, contrast loss, forward-scatter halo |
| Rain | Rain extinction, motion-blurred streaks, refractive droplets on the window |
| Heat Shimmer | Turbulence: log-normal scintillation, angle-of-arrival wander (Ornstein–Uhlenbeck), beam blur |
| Sensor Noise | Shot + read noise, row banding, hot and flickering pixels |
| Mount Vibration | 2–21 Hz multi-tone LOS jitter up to ±0.11°, with exposure smear |
| Sun Glare | Veiling glare gradient near the sun and lens ghosts; the sun disk can enter the FOV while scanning |
| Occlusion | Birds, branches and clouds blocking the beacon (0.25–1.5 s events) |
| Decoy Lights | Street lights / glints (some blinking) plus an uncued second drone with a strobe near the target |

The camera is a 640×480 NIR (850 nm) sensor with a 4°×3° field of view, 1 px ≈ 0.11 mrad. Time of day (Day / Dusk / Night) changes sky radiance, exposure and contrast.

---

## 5. Architecture

```
 FrameSource ──► BeaconDetector ──► LOS Kalman tracker ──► Acquisition FSM ──► pointing reference
 (sim / video /    top-hat, matched     Singer model,         SEARCH → ACQUIRING →          │
  live camera)     filter, CFAR,        adaptive noise,        LOCKED ⇄ COASTING →          ▼
                   shape + contrast     Mahalanobis gating     REACQUIRE            GimbalController ──► GimbalInterface
                   tests                                                             FF + PI, 60 Hz       (sim / serial)

 Vision thread 30 Hz ─────────────────────────────────────────┘      Control thread 60 Hz ───┘
 GUI thread 60 Hz reads immutable snapshots (never blocks either loop)
```

| Package | Role |
|---|---|
| `fsoc/core` | Source-agnostic tracking algorithms. Never sees ground truth. |
| `fsoc/io` | `Frame`, `FrameSource` (`VideoFileSource`, `LiveCameraSource`), `GimbalInterface` (`SimulatedGimbal`, `StaticMount`, `SerialPanTiltGimbal`) |
| `fsoc/sim` | Scene & NIR sensor renderer, 8 patterns, 8 hazards, GPS cue, decoys |
| `fsoc/runtime` | Threaded engine, SIH evaluator, recorder, validation suite |
| `gui` | Pastel PySide6 interface (Live tracking · Analytics · System & inputs) |

### Why these algorithms

- **Detector** — white top-hat + Gaussian matched filter + MAD-based CFAR threshold, then connected components.
  - Components are filtered with intensity-moment elongation and ring-contrast tests.
  - The top-hat removes sky gradients, glare and fog veil. The threshold follows the real noise floor of any camera.
  - Rain streaks, edges and gaps between dark structures are rejected by shape.
  - It runs in about 1 ms, needs no training data, and behaves the same on real frames.
- **Tracker** — Kalman filter in **line-of-sight angles** (gimbal encoder + pixel offset), using a Singer manoeuvring-target model.
  - Working in LOS angles makes the estimate independent of the camera's own motion. That is the property that carries over to a real gimbal.
  - Prediction bridges occlusions (target loss).
  - An innovation whiteness test tells manoeuvres (biased innovations) from jitter (zero-mean innovations). Manoeuvres raise process noise; jitter raises measurement noise.
- **Acquisition** — external cue (GPS/telemetry bearing) → Archimedean spiral over the cue uncertainty → multi-hypothesis confirmation.
  - Hypotheses are scored on cue distance, rate consistency with the cue, and brightness stability. Rejected decoys are remembered.
  - This is the standard FSOC PAT procedure, and it is what keeps decoys from being locked.
- **Association** — Mahalanobis gate plus brightness consistency, adaptive to the observed scintillation.
  - While coasting, the gate is capped and re-association needs two consistent frames, so a single decoy flash cannot capture the track.
  - Re-acquisition searches the prediction first, then the cue cone.
- **Controller** — velocity feed-forward from the Kalman rate + PI feedback, rate- and acceleration-limited, 60 Hz. Feed-forward removes the lag a proportional loop has against a moving target.
- **Threads** — render and control rates never limit each other.

---

## 6. Adding video and hardware (next stages)

Only the frame source and the gimbal change; `TrackingPipeline` and `GimbalController` are reused as-is.

```python
from fsoc.core import TrackingPipeline, GimbalController, CameraIntrinsics
from fsoc.io import VideoFileSource, LiveCameraSource, StaticMount

src = VideoFileSource("benchmark.mp4", hfov_deg=4.0)        # or LiveCameraSource(0, my_gimbal)
pipe = TrackingPipeline(src.intrinsics)
pipe.cfg.require_cue = False                                 # no telemetry: search from bore-sight
while (frame := src.read()) is not None:
    out = pipe.process_frame(frame)                          # state, centroid, track, ROI, SNR…
```

- **Hardware:** implement `GimbalInterface.read_state()` (encoder angles, timestamped) and `command_rate()` in `SerialPanTiltGimbal`. Run the same 60 Hz control tick as `Engine._control_tick`.
- **Timestamps:** frames must carry capture time and the encoder pose at mid-exposure. The tracker is fully timestamp-driven, so frame drops and variable FPS are handled.
- **Calibration:** replace `CameraIntrinsics.from_fov` with calibrated `fx, fy, cx, cy`.

---

## 7. Interface tour

- **Live tracking**
  - Left rail: pattern tiles and hazard switches with intensity sliders.
  - Centre: camera sensor view, with detections, track brackets, ±10 px tolerance ring, scan path and a sub-pixel zoom. Below it, the interactive world view: drag to orbit, scroll to zoom.
  - Right rail: the six mission targets and the test buttons.
- **Analytics** — error timeline with state band, centroid scatter bullseye, SNR/confidence, loop rates vs thresholds, per-stage latency budget. Also session export and the in-app validation suite.
- **System & inputs** — input sources, live pipeline with per-stage timing, design rationale, live tuning.

## 8. Project layout

```
main.py                 entry point (PyInstaller target)
benchmark.py            headless validation CLI
build_exe.ps1           one-command build → dist\FSOC_Beacon_Tracker.exe
FSOC_Beacon_Tracker.spec
fsoc/  core/ io/ sim/ runtime/
gui/   main_window, camera_view, world_view, control_rail, kpi_panel, charts, analytics_page, system_page, theme, widgets
assets/app.ico
_archive/alpha_v0.3_source.zip   previous alpha build (source)
```

The earlier alpha code is kept but is no longer used by the application:

- the `simulation/` package;
- nine superseded `gui/*.py` files (`world_map`, `metrics_panel`, `disturbances_panel`, `scenario_panel`, `reference_panel`, `pipeline_strip`, `graph_widget`, `distance_plot`, `simulation_widget`);
- `dist\FSOC_Beacon_Tracker_alpha_v0.3.exe`.

A zip of that alpha source is in `_archive/`.
