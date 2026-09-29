import { AbsoluteFill, Audio, Easing, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

import { clamp } from "../components";
import { Brackets, Mark, Sky, StatePill, Trace, Wordmark, type Light, lightPos, starField } from "../fsoc";
import { STATE_COLOR, color, font } from "../theme";

// The 10-second launch cut. Three acts, one idea each:
//   0–90    the problem: a naive tracker grabs the brightest light, which is wrong
//   90–210  the solution: every light's brightness history is drawn; only one is a clean 5 Hz square wave
//   210–300 the mark
export const LAUNCH_FRAMES = 300;

const W = 1920;
const H = 1080;
const BEACON = { x: 1010, y: 520 };
const WRONG_AT = 34;
const FLASH_AT = 90;
const ACQ_AT = 150;
const LOCK_AT = 181; // 31 frames after ACQUIRING: the hover case's real 1.03 s
const MARK_AT = 210;

const NAMED: (Light & { label: string })[] = [
  { id: "sat", kind: "sat", x: 1380, y: 300, size: 10, peak: 1, vx: -0.7, label: "sun-lit satellite · steady" },
  { id: "lamp", kind: "lamp", x: 640, y: 660, size: 11, peak: 1, label: "street lamp · steady" },
  { id: "tower", kind: "tower", x: 420, y: 300, size: 9, peak: 1, hz: 0.5, label: "tower light · 0.5 Hz" },
  { id: "decoy", kind: "decoy", x: 1480, y: 770, size: 9, peak: 0.95, hz: 3, label: "rival laser · 3 Hz" },
  { id: "strobe", kind: "strobe", x: 760, y: 220, size: 8, peak: 1, label: "aircraft strobe" },
  { id: "beacon", kind: "beacon", x: BEACON.x, y: BEACON.y, size: 6, peak: 0.75, hz: 5, label: "beacon · 5 Hz · P 1.00" },
];
const LIGHTS: Light[] = [...starField("launch", 220, W, H), ...NAMED];

const sfx = (name: string) => staticFile(`audio/sfx/${name}.wav`);

export function Launch() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // camera: a slow push through act 1, a snap-in at the lock, a rush forward into the mark
  const push = interpolate(frame, [0, FLASH_AT, LOCK_AT, MARK_AT, MARK_AT + 30], [1.0, 1.08, 1.12, 1.16, 3.2], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const worldFade = interpolate(frame, [MARK_AT + 4, MARK_AT + 28], [1, 0], clamp);
  const cold = interpolate(frame, [FLASH_AT - 4, FLASH_AT + 10], [1, 0], clamp); // desaturated before the flash
  const flash = interpolate(frame, [FLASH_AT - 2, FLASH_AT, FLASH_AT + 12], [0, 0.9, 0], clamp);

  return (
    <AbsoluteFill style={{ background: color.night, fontFamily: font.text }}>
      <AbsoluteFill style={{ transform: `scale(${push})`, transformOrigin: `${BEACON.x}px ${BEACON.y}px`, opacity: worldFade, filter: `saturate(${1 - cold * 0.45}) brightness(${1 - cold * 0.1})` }}>
        <Sky lights={LIGHTS} frame={frame} width={W} height={H} noise={0.06} />
        <Naive frame={frame} />
        <Traces frame={frame} />
        <Lock frame={frame} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "#fff", opacity: flash }} />
      <Captions frame={frame} />
      <Close frame={frame} fps={fps} />

      <Audio src={staticFile("audio/pad.m4a")} volume={(f) => interpolate(f, [0, 20, 270, 300], [0, 0.35, 0.35, 0], clamp)} />
      <Sequence from={WRONG_AT}><Audio src={sfx("alert")} volume={0.45} /></Sequence>
      <Sequence from={FLASH_AT - 6}><Audio src={sfx("whoosh")} volume={0.5} /></Sequence>
      <Sequence from={FLASH_AT + 8}><Audio src={sfx("scan")} volume={0.35} /></Sequence>
      {new Array(9).fill(0).map((_, i) => (
        <Sequence key={i} from={ACQ_AT + i * 6}><Audio src={sfx("tick")} volume={0.25} /></Sequence>
      ))}
      <Sequence from={LOCK_AT}><Audio src={sfx("chime")} volume={0.55} /></Sequence>
      <Sequence from={MARK_AT + 18}><Audio src={sfx("impact")} volume={0.75} /></Sequence>
    </AbsoluteFill>
  );
}

// Act 1: a reticle that trusts brightness. It hops to the brightest light and turns red.
function Naive({ frame }: { frame: number }) {
  if (frame > FLASH_AT) return null;
  const sat = lightPos(NAMED[0], frame);
  const start = { x: W / 2, y: H / 2 };
  const t = interpolate(frame, [8, WRONG_AT], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const x = start.x + (sat.x - start.x) * t;
  const y = start.y + (sat.y - start.y) * t;
  const wrong = frame >= WRONG_AT;
  const shake = wrong ? Math.sin(frame * 2.3) * interpolate(frame, [WRONG_AT, WRONG_AT + 14], [6, 0], clamp) : 0;
  return (
    <>
      <Brackets x={x + shake} y={y} size={70} tone={wrong ? color.bad : "#8a909c"} weight={3} progress={interpolate(frame, [4, 14], [0, 1], clamp)} />
      {wrong && (
        <div style={{ position: "absolute", left: x + 56, top: y - 58, fontFamily: font.mono, fontSize: 24, fontWeight: 700, color: color.bad, opacity: interpolate(frame, [WRONG_AT, WRONG_AT + 6], [0, 1], clamp) }}>
          brightest ≠ beacon
        </div>
      )}
    </>
  );
}

// Act 2: every named light grows a brightness trace. Only the beacon's is a clean square wave.
function Traces({ frame }: { frame: number }) {
  if (frame < FLASH_AT + 6) return null;
  return (
    <>
      {NAMED.map((light, i) => {
        const p = lightPos(light, frame);
        const isBeacon = light.kind === "beacon";
        const appear = interpolate(frame, [FLASH_AT + 8 + i * 4, FLASH_AT + 22 + i * 4], [0, 1], clamp);
        const dim = isBeacon ? 1 : interpolate(frame, [LOCK_AT - 10, LOCK_AT + 6], [1, 0.3], clamp);
        const tone = isBeacon ? (frame >= LOCK_AT ? color.ok : "#8fd6ff") : "#c9cfdb";
        return (
          <div key={light.id} style={{ position: "absolute", left: p.x + 28, top: p.y + 22, opacity: appear * dim, transform: `translateY(${(1 - appear) * 16}px)` }}>
            <div style={{ fontFamily: font.mono, fontSize: 19, fontWeight: 600, color: tone, marginBottom: 6, whiteSpace: "nowrap", textShadow: "0 1px 8px #000" }}>{light.label}</div>
            <div style={{ padding: "6px 10px", borderRadius: 10, background: "rgba(11,17,32,0.6)", border: `1px solid ${isBeacon ? `${tone}88` : "#2a3550"}` }}>
              <Trace light={light} frame={frame} width={200} height={38} samples={48} tone={tone} strokeWidth={isBeacon ? 2.6 : 1.8} />
            </div>
          </div>
        );
      })}
    </>
  );
}

function Lock({ frame }: { frame: number }) {
  if (frame < ACQ_AT) return null;
  const state = frame >= LOCK_AT ? "LOCKED" : "ACQUIRING";
  const { fps } = { fps: 30 };
  const snap = spring({ frame: frame - ACQ_AT, fps, config: { damping: 14, stiffness: 160 } });
  const locked = spring({ frame: frame - LOCK_AT, fps, config: { damping: 12, stiffness: 200 } });
  const ring = interpolate(frame, [LOCK_AT, LOCK_AT + 18], [0, 1], clamp);
  return (
    <>
      <Brackets x={BEACON.x} y={BEACON.y} size={64 - locked * 12} progress={snap} tone={STATE_COLOR[state]} weight={4} spin={(1 - snap) * 45} />
      {frame >= LOCK_AT && ring < 1 && (
        <div style={{ position: "absolute", left: BEACON.x - 40, top: BEACON.y - 40, width: 80, height: 80, borderRadius: "50%", border: `3px solid ${color.ok}`, transform: `scale(${1 + ring * 2.2})`, opacity: 1 - ring }} />
      )}
      <div style={{ position: "absolute", left: BEACON.x - 120, top: BEACON.y - 110, opacity: snap }}>
        <StatePill state={state} size={20} />
      </div>
    </>
  );
}

function Captions({ frame }: { frame: number }) {
  const beats = [
    { from: 6, to: FLASH_AT - 4, text: "In a sky full of lights…", tone: "#e6ebf5" },
    { from: FLASH_AT + 20, to: LOCK_AT - 2, text: "…find the one that blinks.", tone: "#e6ebf5" },
    { from: LOCK_AT + 2, to: MARK_AT, text: "Locked in 1.03 s.", tone: color.ok },
  ];
  return (
    <>
      {beats.map((beat) => {
        const inT = interpolate(frame, [beat.from, beat.from + 10], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
        const outT = interpolate(frame, [beat.to - 8, beat.to], [1, 0], clamp);
        if (frame < beat.from || frame > beat.to) return null;
        return (
          <div
            key={beat.text}
            style={{
              position: "absolute",
              left: 120,
              bottom: 110,
              fontFamily: font.display,
              fontWeight: 600,
              fontSize: 76,
              letterSpacing: "-0.03em",
              color: beat.tone,
              opacity: inT * outT,
              transform: `translateY(${(1 - inT) * 30}px)`,
              filter: `blur(${(1 - inT) * 8}px)`,
              textShadow: "0 4px 30px rgba(0,0,0,0.6)",
            }}
          >
            {beat.text}
          </div>
        );
      })}
    </>
  );
}

function Close({ frame, fps }: { frame: number; fps: number }) {
  if (frame < MARK_AT + 10) return null;
  const draw = interpolate(frame, [MARK_AT + 14, MARK_AT + 40], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const bg = interpolate(frame, [MARK_AT + 10, MARK_AT + 26], [0, 1], clamp);
  const pop = spring({ frame: frame - MARK_AT - 14, fps, config: { damping: 13, stiffness: 150 } });
  const tag = interpolate(frame, [MARK_AT + 52, MARK_AT + 64], [0, 1], clamp);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", background: `radial-gradient(ellipse at 50% 45%, rgba(20,28,48,${bg}), rgba(11,17,32,${bg}) 70%)` }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 34 }}>
        <div style={{ transform: `scale(${0.6 + pop * 0.4})` }}>
          <Mark size={170} draw={draw} locked={frame > MARK_AT + 44 ? 1 : 0} />
        </div>
        <Wordmark size={160} delay={MARK_AT + 26} tone="#f3f6fb" />
        <div style={{ fontFamily: font.mono, fontSize: 32, fontWeight: 600, letterSpacing: "0.2em", color: color.accent, opacity: tag, transform: `translateY(${(1 - tag) * 12}px)` }}>
          POINT · ACQUIRE · TRACK
        </div>
      </div>
    </AbsoluteFill>
  );
}
