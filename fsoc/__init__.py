"""FSOC coarse Pointing-Acquisition-Tracking (PAT) system — SIH26169.

Package layout
  fsoc.core     Source-agnostic tracking algorithms (detector, LOS Kalman tracker,
                acquisition state machine, gimbal controller). Never sees ground truth.
  fsoc.io       Hardware abstraction: FrameSource (simulation / video file / live camera)
                and GimbalInterface (simulated / serial pan-tilt / virtual crop).
  fsoc.sim      Physically-motivated simulator: 8 beacon patterns, 8 hazards, sensor model.
  fsoc.runtime  Threaded engine (decoupled vision & control loops), SIH evaluator, logging,
                headless validation suite.
"""

__version__ = "1.0.0"

# OpenCV's multi-threaded kernels (GaussianBlur, morphologyEx, moments, ...) do not guarantee a
# fixed reduction order, so two runs of the identical (seed, pattern, hazards) case can render
# frames that differ by a few DN here and there — usually harmless, but this is a closed-loop
# acquisition state machine, and on rare frames a few DN is enough to flip which side of a gate
# threshold a candidate falls on, cascading into a completely different track. Forcing single-
# threaded OpenCV makes every run of the same configuration bit-for-bit reproducible, which
# matters far more here than the (negligible, at 640x480) speed cost — the validation suite in
# particular must mean the same thing every time it is run.
import cv2 as _cv2
_cv2.setNumThreads(1)
