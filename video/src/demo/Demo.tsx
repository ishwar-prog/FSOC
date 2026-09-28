import { AbsoluteFill, Easing, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";

import { clamp } from "../components";
import { color, font } from "../theme";

// The README demo: a real app recording (tools/record_demo.py → public/demo/raw.mp4), trimmed and framed.
// Scenario: LEO pass, 80 % decoy satellites, 30 % shimmer. Cold start, then a 2.5 s beacon blockage.
// The recorder grabs slower than real time, so the clip plays at roughly 2.4× the app's clock.

type Beat = { at: number; text: string; tone?: string };
type Segment = { from: number; frames: number; zoom: number; origin: [number, number]; beats: Beat[] };

const SEGMENTS: Segment[] = [
  {
    from: 0,
    frames: 345,
    zoom: 1.45,
    origin: [975, 330],
    beats: [
      { at: 4, text: "Cold start · LEO pass · dense satellite field" },
      { at: 62, text: "Beacon picked out by its blink · locked", tone: color.ok },
      { at: 150, text: "Every other light rejected · ID 100 %", tone: color.ok },
      { at: 262, text: "Beacon blocked · coasting on the orbit prediction", tone: color.warn },
      { at: 300, text: "Re-acquired", tone: color.ok },
    ],
  },
  {
    from: 2070,
    frames: 180,
    zoom: 1.3,
    origin: [1920, 100],
    beats: [{ at: 10, text: "All six SIH targets pass", tone: color.ok }],
  },
];

const FADE = 12;
const STARTS = SEGMENTS.map((_, i) => SEGMENTS.slice(0, i).reduce((t, s) => t + s.frames - FADE, 0));
export const DEMO_FRAMES = STARTS[STARTS.length - 1] + SEGMENTS[SEGMENTS.length - 1].frames;

export function Demo() {
  return (
    <AbsoluteFill style={{ background: color.bg }}>
      {SEGMENTS.map((segment, i) => (
        <Sequence key={i} from={STARTS[i]} durationInFrames={segment.frames}>
          <Shot segment={segment} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
}

function Shot({ segment }: { segment: Segment }) {
  const frame = useCurrentFrame();
  const inT = interpolate(frame, [0, FADE], [0, 1], clamp);
  const outT = interpolate(frame, [segment.frames - FADE, segment.frames], [1, 0], clamp);
  const push = interpolate(frame, [0, 40, segment.frames], [1, segment.zoom, segment.zoom + 0.05], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const beat = [...segment.beats].reverse().find((b) => frame >= b.at);
  return (
    <AbsoluteFill style={{ opacity: inT * outT }}>
      <AbsoluteFill style={{ transform: `scale(${push})`, transformOrigin: `${segment.origin[0]}px ${segment.origin[1]}px` }}>
        <OffthreadVideo src={staticFile("demo/raw.mp4")} startFrom={segment.from} muted />
      </AbsoluteFill>
      {beat && <Caption key={beat.at} beat={beat} frame={frame} />}
    </AbsoluteFill>
  );
}

function Caption({ beat, frame }: { beat: Beat; frame: number }) {
  const t = interpolate(frame, [beat.at, beat.at + 10], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const tone = beat.tone ?? "#f3f6fb";
  return (
    <div
      style={{
        position: "absolute",
        left: 70,
        bottom: 64,
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "18px 28px",
        borderRadius: 18,
        background: "rgba(11,17,32,0.88)",
        boxShadow: "0 20px 50px -20px rgba(0,0,0,0.6)",
        fontFamily: font.display,
        fontSize: 40,
        fontWeight: 600,
        letterSpacing: "-0.02em",
        color: "#f3f6fb",
        opacity: t,
        transform: `translateY(${(1 - t) * 20}px)`,
      }}
    >
      <span style={{ width: 14, height: 14, borderRadius: "50%", background: tone }} />
      {beat.text}
    </div>
  );
}
