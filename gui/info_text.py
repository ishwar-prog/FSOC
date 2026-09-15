"""Plain-language explanations shown by the (i) buttons. Kept in one place so they stay consistent."""

INFO = {
    # ---- screens
    "camera": "<b>Camera sensor</b><br>The live picture from the tracking camera on Terminal A — "
              "a near-infrared camera that sees a 4° × 3° patch of sky.<br><br>The tracker works only "
              "from this image. The simulator's hidden “true position” is used just to score the results.",
    "world": "<b>World view</b><br>A 3-D picture of the link: your ground terminal (A) points its camera at "
             "the remote terminal (B).<br><br>• Drag <b>Terminal B</b> to steer it<br>• Drag "
             "<b>Terminal A</b> to move your station<br>• Drag empty space to rotate, scroll to zoom, "
             "double-click to reset.",
    "space_view": "<b>Space view</b><br>A schematic (not to scale) of the satellite pass over your ground "
                  "station, and a sky plot showing where it is in the sky.<br><br>The station points "
                  "using the satellite's predicted orbit (ephemeris), then locks onto its beacon — the "
                  "same method NASA used with the OPALS laser terminal on the ISS.",
    # ---- right rail
    "targets": "<b>Mission targets</b><br>The six numbers the SIH problem statement asks for, measured "
               "live and marked PASS or FAIL.",
    "identity": "<b>Beacon identity</b><br>The beacon is not always the brightest light. Stars twinkle "
                "randomly, tower lights blink slowly, satellites glint, street lights stay steady.<br><br>"
                "The tracker watches how every light's brightness changes over time. A beacon blinks in a "
                "steady rhythm — its <i>signature</i>. Once locked, the system <b>learns</b> that exact "
                "rhythm and ignores look-alikes. Nothing is pre-set, so it works the same on recorded video.",
    "tests": "<b>Test the targets</b><br>Buttons that cause the events being measured, so you can watch "
             "the numbers react.",
    "acquisition": "<b>Acquisition time</b><br>How long it takes, from a cold start, to find the beacon "
                   "and confirm a lock. Target: 2 seconds or less.",
    "tracking_error": "<b>Tracking error</b><br>How far, in pixels, the detected beacon centre is from its "
                      "true centre in the image. Smaller is better; target 10 pixels or less.",
    "target_loss": "<b>Target loss</b><br>The share of time without a valid lock. Short blinks the "
                   "tracker can predict through do not count. Target: under 5 %.",
    "reacquisition": "<b>Re-acquisition</b><br>After the beacon is lost (for example, blocked by a "
                     "cloud), how quickly the lock comes back once it is visible again. Target: 1 s or less.",
    "processing": "<b>Processing speed</b><br>How many camera frames per second the whole detection and "
                  "tracking pipeline handles. Target: 20 or more.",
    "camera_rate": "<b>Camera update rate</b><br>How often the screen redraws and how often the gimbal "
                   "motors get new commands. They run separately so neither slows the other. "
                   "Target: 30 and 20 updates per second.",
    # ---- remote terminal
    "platform": "<b>Terminal type</b><br>What carries the remote terminal: a drone, an aircraft, a ship, a "
                "satellite or a space station. Each moves in its own realistic way.",
    "motion": "<b>Movement</b><br>How the remote terminal moves. Choose <i>Manual Drive</i> — or simply "
              "drag Terminal B in the world view — to steer it yourself.",
    "controls": "<b>Motion controls</b><br>Change the remote terminal while it runs. Every change blends in "
                "smoothly, the way a real vehicle would respond.",
    "speed": "<b>Speed</b><br>How fast the terminal moves along its path (1× is realistic speed).",
    "distance": "<b>Distance</b><br>How far the remote terminal is from your station. Further away means "
                "a fainter, smaller beacon.",
    "bearing": "<b>Direction</b><br>Turns the whole flight area left or right as seen from your station.",
    "altitude": "<b>Altitude</b><br>Raises or lowers the terminal compared with its normal height.",
    "variation": "<b>Real-world variation</b><br>Wind gusts, course wander and speed changes — or, for "
                 "spacecraft, attitude wobble that makes the beacon flicker.",
    "time_warp": "<b>Time speed</b><br>A real satellite pass lasts several minutes. Speed it up to see a "
                 "whole pass sooner.",
    "orbit_alt": "<b>Orbit altitude</b><br>Height of the satellite above Earth. Lower orbits cross the sky "
                 "faster and are closer.",
    "max_el": "<b>Highest point of the pass</b><br>How high in the sky the satellite climbs. 90° would "
              "be straight overhead.",
    "heading": "<b>Pass direction</b><br>The compass direction the satellite travels across the sky.",
    "beacon": "<b>Beacon signal</b><br>The light the remote terminal sends so it can be found. Real "
              "beacons blink rapidly on and off in a fixed rhythm. The tracker is not told these values — "
              "it has to learn them.",
    "freq": "<b>Blink rate</b><br>How many times per second the beacon switches on and off.",
    "brightness": "<b>Beacon brightness</b><br>Turn it down to test that the tracker still finds the beacon "
                  "when other lights are brighter.",
    "depth": "<b>Blink depth</b><br>How completely the beacon switches off. 100 % means fully off; 0 % "
             "means a steady light with no rhythm.",
    # ---- ground terminal
    "mount": "<b>Mount</b><br>What your own terminal sits on. Vehicles and ships move and shake; "
             "stabilisers remove most — but not all — of that motion.",
    "position": "<b>Position</b><br>Where your station stands. You can also drag Terminal A in the world view.",
    "east": "<b>East offset</b><br>Moves your station left or right.",
    "north": "<b>North offset</b><br>Moves your station forward or back.",
    "height": "<b>Mast height</b><br>How high the camera sits above the ground.",
    "gimbal": "<b>Gimbal</b><br>The motorised mount that turns the camera left/right and up/down.",
    "slew": "<b>Maximum turn speed</b><br>The fastest the gimbal is allowed to swing the camera.",
    # ---- environment
    "tod": "<b>Time of day</b><br>Changes sky brightness. Satellites are usually tracked at night or dusk, "
           "when the sky is dark.",
    "hazards": "<b>Hazards</b><br>Real-world problems that make tracking harder. Switch on any "
               "combination and set how strong each one is.",
    # ---- telemetry
    "telemetry": "<b>Live readouts</b><br>What the tracker is doing right now.",
    # ---- analytics
    "timeline": "<b>Tracking error over time</b><br>The purple line is the tracking error; the dashed "
                "line is the 10 px target. The coloured strip underneath shows the tracker state.",
    "scatter": "<b>Centroid scatter</b><br>Each dot shows how far the detected centre was from the true "
               "centre. Dots packed near the middle mean high accuracy.",
    "signal": "<b>Signal quality</b><br>How strong the beacon is compared with background noise, and how "
              "sure the tracker is that it is looking at the real beacon.",
    "rates": "<b>Loop rates</b><br>Frames per second for the camera pipeline, the gimbal control loop and "
             "the screen, with their target lines.",
    "budget": "<b>Processing budget</b><br>Time spent on each step for every frame. Everything must fit in "
              "50 ms to reach 20 frames per second.",
    "suite": "<b>Validation suite</b><br>Automatically runs every terminal type and every hazard from a cold "
             "start and checks all six targets.",
    # ---- readout terms (camera strip)
    "ro_state": "<b>State</b><br>SEARCH scans for the beacon · ACQUIRING checks a candidate · LOCKED "
                "follows it · COASTING predicts through a short gap · REACQUIRE looks for it again.",
    "ro_age": "<b>Time in state</b><br>How long the tracker has been in its current state.",
    "ro_snr": "<b>Beacon SNR</b><br>Signal-to-noise ratio: how much brighter the beacon spot is than the "
              "random speckle of the camera. Below about 10 it is hard to see.",
    "ro_idp": "<b>Beacon identity</b><br>How sure the tracker is that the light it follows is the real "
              "beacon, judged from its blink rhythm.",
    "ro_cerr": "<b>Centroid error</b><br>Distance in pixels between where the tracker thinks the beacon "
               "centre is and where it really is. 1 pixel ≈ 0.006°.",
    "ro_perr": "<b>Pointing error</b><br>How far the camera centre is from the beacon — how well the gimbal "
               "keeps it in the middle.",
    "ro_gimbal": "<b>Gimbal az / el</b><br>Where the camera points: azimuth is the compass direction, "
                 "elevation is the angle above the horizon.",
    "ro_rate": "<b>Slew rate</b><br>How fast the gimbal is turning right now, in degrees per second.",
    "ro_range": "<b>Range</b><br>Distance from your station to the remote terminal.",
    "ro_cands": "<b>Lights in view</b><br>How many point lights the detector found in the current picture — "
                "the beacon plus stars, lamps, glints or satellites.",
}


def tip(key: str) -> str:
    return INFO.get(key, "")
