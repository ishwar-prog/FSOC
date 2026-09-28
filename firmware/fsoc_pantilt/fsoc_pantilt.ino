/*
  COSTA — pan/tilt servo head (Arduino Uno / Nano)

  Wiring
    D9  -> pan  servo signal (SG90)
    D10 -> tilt servo signal (SG90)
    Servo power from a separate 5 V supply (>= 2 A), grounds tied to the Arduino GND.
    Powering two SG90s from the Arduino's 5 V pin browns the board out when they start
    together — the classic cause of random resets and jitter.

  Mount geometry (this rig)
    Pan : 90 deg = straight ahead.
    Tilt: 130 deg = camera level (face perpendicular to the ground); a larger angle tilts
          the camera down, a smaller one tilts it up.

  Serial protocol, 115200 baud, one ASCII line per message
    PC -> head   "A <pan> <tilt>\n"   target angles in hundredths of a degree (0..18000)
                 "?\n"                 query
    head -> PC   "FSOC-PT 1\n"         banner, once at boot after homing
                 "S <pan> <tilt>\n"    reply to "?": current output angles, hundredths of a degree

  The PC does the tracking and all trajectory shaping (rate and acceleration limits). This
  sketch only turns angles into pulses with sub-degree resolution and slew-limits every move,
  so no command — a first command after connecting, a glitch on the line — can ever slam the
  head across its travel.
*/

#include <Servo.h>

// ---- per-servo calibration: pulse widths at 0 and 180 degrees (SG90 typical: 500 / 2400 us)
const int PAN_PIN = 9;
const int TILT_PIN = 10;
const float PULSE_MIN_US = 500.0;
const float PULSE_MAX_US = 2400.0;

// ---- travel limits (degrees). Tilt stays clear of the zenith and of the mount's own base.
const float PAN_MIN = 5.0, PAN_MAX = 175.0;
const float TILT_MIN = 55.0, TILT_MAX = 175.0;

const float PAN_HOME = 90.0;
const float TILT_HOME = 130.0;

// ---- motion
const float MAX_SPEED_DEG_S = 360.0;   // safety slew limit; the PC normally moves far slower
const unsigned long TICK_US = 5000;    // 200 Hz output update

Servo pan, tilt;
float panOut = PAN_HOME, tiltOut = TILT_HOME;       // what the servos are being driven to now
float panTarget = PAN_HOME, tiltTarget = TILT_HOME; // what the PC asked for
unsigned long lastTick = 0;

char line[40];
byte lineLen = 0;

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

static void writeServo(Servo &s, float deg) {
  float us = PULSE_MIN_US + deg * (PULSE_MAX_US - PULSE_MIN_US) / 180.0;
  s.writeMicroseconds((int)(us + 0.5));
}

static float approach(float cur, float target, float maxStep) {
  float d = target - cur;
  if (d > maxStep) return cur + maxStep;
  if (d < -maxStep) return cur - maxStep;
  return target;
}

static void handleLine(char *s) {
  if (s[0] == '?') {
    Serial.print(F("S "));
    Serial.print((long)(panOut * 100.0));
    Serial.print(' ');
    Serial.println((long)(tiltOut * 100.0));
    return;
  }
  if (s[0] != 'A') return;
  char *p = s + 1;
  long a = strtol(p, &p, 10);
  if (*p == '\0') return;                 // malformed: needs two numbers
  long b = strtol(p, &p, 10);
  panTarget = clampf(a / 100.0, PAN_MIN, PAN_MAX);
  tiltTarget = clampf(b / 100.0, TILT_MIN, TILT_MAX);
}

void setup() {
  Serial.begin(115200);
  pan.attach(PAN_PIN, (int)PULSE_MIN_US, (int)PULSE_MAX_US);
  tilt.attach(TILT_PIN, (int)PULSE_MIN_US, (int)PULSE_MAX_US);
  writeServo(pan, panOut);
  writeServo(tilt, tiltOut);
  delay(600);                             // let the head reach home before announcing
  Serial.println(F("FSOC-PT 1"));
  lastTick = micros();
}

void loop() {
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (lineLen) {
        line[lineLen] = '\0';
        handleLine(line);
        lineLen = 0;
      }
    } else if (lineLen < sizeof(line) - 1) {
      line[lineLen++] = ch;
    } else {
      lineLen = 0;                        // overlong line: drop it
    }
  }

  unsigned long now = micros();
  if (now - lastTick >= TICK_US) {
    float dt = (now - lastTick) * 1e-6;
    lastTick = now;
    float step = MAX_SPEED_DEG_S * dt;
    panOut = approach(panOut, panTarget, step);
    tiltOut = approach(tiltOut, tiltTarget, step);
    writeServo(pan, panOut);
    writeServo(tilt, tiltOut);
  }
}
