"""Check the rig end to end without the GUI: camera, LED, blink, servos.

    python tools/hw_check.py --camera 1 --port COM5

Prints a verdict for each stage and writes hw_check_*.png so a frame can be looked at.
Nothing here is used by the application; it exists to answer "why can't it see my beacon?".
"""

import argparse
import math
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fsoc.core.geometry import CameraIntrinsics          # noqa: E402
from fsoc.core.video import VideoBeaconDetector          # noqa: E402
from fsoc.io.servo import SerialLink, ServoGeometry, ServoPanTiltGimbal   # noqa: E402
from fsoc.io.sources import LiveCameraSource             # noqa: E402

OK, BAD, MEH = "  OK  ", " FAIL ", " ~~~  "


def say(tag, text):
    print(f"[{tag}] {text}", flush=True)


def check_camera(index, seconds, out_dir):
    say("....", f"opening camera {index} …")
    try:
        cam = LiveCameraSource(index, hfov_deg=60.0)
    except IOError as ex:
        say(BAD, f"camera {index}: {ex}")
        return None, None
    say(OK, f"camera {index} open, processing at {cam.size[0]}x{cam.size[1]}, luma='{cam.luma}'")

    frames, t0, last = [], time.perf_counter(), -1
    while time.perf_counter() - t0 < seconds:
        got = cam.latest(time.perf_counter())
        if got is not None and got[2] != last:
            last = got[2]
            frames.append((time.perf_counter(), got[0].copy()))
        else:
            time.sleep(0.002)
    if len(frames) < 10:
        say(BAD, f"only {len(frames)} frames in {seconds:.0f} s — the camera is not delivering")
        cam.close()
        return None, None
    fps = (len(frames) - 1) / (frames[-1][0] - frames[0][0])
    say(OK if fps >= 20 else MEH, f"{len(frames)} frames, {fps:.1f} FPS")
    stack = np.stack([f[1] for f in frames])
    say("....", f"image level: mean {stack.mean():.0f}, max {stack.max()}, "
                f"{100.0 * (stack >= 250).mean():.2f}% of pixels saturated")
    cv2.imwrite(os.path.join(out_dir, "hw_check_frame.png"), frames[len(frames) // 2][1])
    return cam, frames


def check_beacon(frames, out_dir):
    """Find the blinking light: the pixel whose brightness swings most over the clip."""
    stack = np.stack([f[1] for f in frames]).astype(np.float32)
    t = np.array([f[0] for f in frames])
    swing = stack.max(axis=0) - stack.min(axis=0)
    swing_b = cv2.GaussianBlur(swing, (0, 0), 1.2)
    y, x = np.unravel_index(int(np.argmax(swing_b)), swing_b.shape)
    amp = float(swing_b[y, x])
    cv2.imwrite(os.path.join(out_dir, "hw_check_blink.png"),
                np.clip(swing_b * (255.0 / max(amp, 1.0)), 0, 255).astype(np.uint8))
    if amp < 25:
        say(BAD, f"nothing in view blinks (strongest swing {amp:.0f} DN at {x},{y}). "
                 "Is the LED on, in frame, and switching fully off?")
        return None
    # background-subtracted, the way the identifier measures it: a bright room behind the LED
    # otherwise hides the modulation
    core = stack[:, max(0, y - 1):y + 2, max(0, x - 1):x + 2].mean(axis=(1, 2))
    r = 9
    ring = stack[:, max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]
    bg = np.median(ring.reshape(len(stack), -1), axis=1)
    series = np.maximum(core - bg, 0.0)
    fs = (len(t) - 1) / (t[-1] - t[0])
    sig = series - series.mean()
    n = len(sig)
    spec = np.abs(np.fft.rfft(sig * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    band = (freqs > 0.7) & (freqs < min(12.0, fs / 2 - 0.5))
    if not band.any():
        return None
    f0 = float(freqs[band][int(np.argmax(spec[band]))])
    lo, hi = float(np.percentile(series, 10)), float(np.percentile(series, 90))
    depth = (hi - lo) / max(hi + lo, 1e-6)
    say(OK, f"blinking light at pixel ({x},{y}): {f0:.1f} Hz, depth {depth * 100:.0f}%, "
            f"swing {amp:.0f} DN above background")
    if not 2.0 <= f0 <= 8.0:
        say(MEH, f"{f0:.1f} Hz is outside the 2-8 Hz the tracker expects")
    if depth < 0.6:
        say(MEH, f"modulation depth {depth * 100:.0f}% is shallow — the LED may not be switching fully off, "
                 "or the camera's auto-exposure is fighting it")
    return x, y, f0


def check_detector(frames, spot, out_dir):
    img = None
    for _t, f in frames:                       # a frame with the LED lit
        if spot is None or f[spot[1], spot[0]] > 0:
            img = f
            if spot is None or f[spot[1], spot[0]] >= 0.8 * max(g[spot[1], spot[0]] for _t2, g in frames):
                break
    h, w = img.shape[:2]
    f = 160.0 * 180.0 / math.pi
    det = VideoBeaconDetector(CameraIntrinsics(w, h, f, f, w / 2.0, h / 2.0))
    det.CONSOLIDATE = True
    res = det.detect(img)
    say("....", f"detector sees {len(res.candidates)} lights, noise sigma {res.noise_sigma:.1f} DN")
    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for c in res.candidates:
        cv2.circle(vis, (int(c.x), int(c.y)), 12, (60, 200, 60), 1)
    hit = None
    if spot is not None:
        cv2.drawMarker(vis, spot[:2], (0, 90, 255), cv2.MARKER_CROSS, 22, 2)
        near = sorted(res.candidates, key=lambda c: math.hypot(c.x - spot[0], c.y - spot[1]))
        hit = near[0] if near and math.hypot(near[0].x - spot[0], near[0].y - spot[1]) < 12 else None
        if hit is not None:
            say(OK, f"the blinking light IS detected: SNR {hit.snr:.1f}, area {hit.area:.0f} px, "
                    f"peak {hit.peak:.0f} DN")
        else:
            probed = det.probe(img, spot[0], spot[1], 40)
            say(BAD, "the blinking light is NOT detected by the automatic gates"
                     + (f" (probe measures SNR {probed.snr:.1f}, peak {probed.peak:.0f} DN — "
                        "clicking it in the camera view will still track it)" if probed else ""))
    cv2.imwrite(os.path.join(out_dir, "hw_check_detections.png"), vis)
    return hit


def check_head(port, out_dir):
    if not port:
        say(MEH, "no serial port given — skipping the pan/tilt head")
        return
    say("....", f"opening {port} …")
    try:
        link = SerialLink(port)
    except IOError as ex:
        say(BAD, f"{port}: {ex}")
        return
    say(OK, f"{port}: firmware answered")
    servo = ServoPanTiltGimbal(link, ServoGeometry())
    t = time.perf_counter()
    servo.advance(t)
    for target in ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (0.0, 0.0)):
        servo.glide_to(*target)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 1.2:
            servo.advance(time.perf_counter())
            time.sleep(0.005)
        pan, tilt = servo.servo_angles()
        say("....", f"commanded az/el {target} → servos pan {pan:.1f}°, tilt {tilt:.1f}°")
    say(OK, "head moved through pan and tilt — watch that it physically moved, and that "
            "tilt 130° puts the camera level")
    servo.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--port", default=None)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--out", default=os.getcwd())
    a = ap.parse_args()
    print(f"\nFSOC rig check — camera {a.camera}, port {a.port or 'none'}\n" + "-" * 62)
    cam, frames = check_camera(a.camera, a.seconds, a.out)
    if frames is not None:
        spot = check_beacon(frames, a.out)
        check_detector(frames, spot, a.out)
    if cam is not None:
        cam.close()
    check_head(a.port, a.out)
    print("-" * 62)
    print(f"images written to {a.out}: hw_check_frame.png (what the camera sees), "
          f"hw_check_blink.png (what blinks), hw_check_detections.png (what the detector finds)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
