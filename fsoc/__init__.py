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
