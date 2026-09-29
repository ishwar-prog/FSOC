import type { ComponentType } from "react";
import { AbsoluteFill, Audio, Easing, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";

import { clamp } from "./components";
import { BlinkScene, CloseScene, HazardsScene, LinkScene, LockScene, LogoScene, ProofScene, SkyScene, TerminalsScene } from "./scenes";

// Scene order, durations and sound cues. The only place to retime the video.
const OVERLAP = 12;

type Cue = { at: number; sound: string; volume?: number };
type SceneSpec = { name: string; frames: number; Scene: ComponentType; cues: Cue[] };

const SCENES: SceneSpec[] = [
  { name: "link", frames: 120, Scene: LinkScene, cues: [{ at: 54, sound: "alert", volume: 0.4 }, { at: 106, sound: "whoosh", volume: 0.35 }] },
  { name: "logo", frames: 80, Scene: LogoScene, cues: [{ at: 0, sound: "impact", volume: 0.8 }, { at: 30, sound: "chime", volume: 0.35 }] },
  { name: "sky", frames: 180, Scene: SkyScene, cues: [{ at: 8, sound: "scan", volume: 0.35 }, ...[40, 52, 64, 76, 88, 100].map((at) => ({ at, sound: "tick", volume: 0.35 })), { at: 132, sound: "whoosh", volume: 0.3 }] },
  { name: "blink", frames: 200, Scene: BlinkScene, cues: [...[10, 16, 22, 28, 34].map((at) => ({ at, sound: "tick", volume: 0.3 })), { at: 130, sound: "chime", volume: 0.45 }] },
  { name: "lock", frames: 180, Scene: LockScene, cues: [{ at: 20, sound: "scan", volume: 0.35 }, { at: 47, sound: "chime", volume: 0.55 }] },
  { name: "terminals", frames: 150, Scene: TerminalsScene, cues: [0, 1, 2, 3, 4, 5].map((i) => ({ at: 14 + i * 5, sound: "tick", volume: 0.35 })) },
  { name: "hazards", frames: 150, Scene: HazardsScene, cues: [...[0, 1, 2, 3, 4, 5, 6].map((i) => ({ at: 16 + i * 12, sound: "tick", volume: 0.3 })), { at: 118, sound: "chime", volume: 0.45 }] },
  { name: "proof", frames: 160, Scene: ProofScene, cues: [{ at: 36, sound: "scan", volume: 0.3 }, { at: 112, sound: "chime", volume: 0.55 }] },
  { name: "close", frames: 110, Scene: CloseScene, cues: [{ at: 0, sound: "impact", volume: 0.65 }] },
];

const STARTS = SCENES.map((_, index) => SCENES.slice(0, index).reduce((total, scene) => total + scene.frames - OVERLAP, 0));
export const INTRO_FRAMES = STARTS[STARTS.length - 1] + SCENES[SCENES.length - 1].frames;

// Dolly between scenes: the outgoing scene pushes in and fades, the incoming one settles from slightly large.
function Dolly({ frames, children }: { frames: number; children: React.ReactNode }) {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, OVERLAP], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const exit = interpolate(frame, [frames - OVERLAP, frames], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  const scale = 1 + (1 - enter) * 0.06 + exit * 0.08;
  return <AbsoluteFill style={{ opacity: enter * (1 - exit), transform: `scale(${scale})`, filter: `blur(${(1 - enter) * 8 + exit * 8}px)` }}>{children}</AbsoluteFill>;
}

export function Intro() {
  return (
    <AbsoluteFill style={{ background: "#f1f2f6" }}>
      {SCENES.map(({ name, frames, Scene, cues }, index) => (
        <Sequence key={name} name={name} from={STARTS[index]} durationInFrames={frames}>
          <Dolly frames={frames}>
            <Scene />
          </Dolly>
          {cues.map((cue, i) => (
            <Sequence key={i} from={cue.at}>
              <Audio src={staticFile(`audio/sfx/${cue.sound}.wav`)} volume={cue.volume ?? 0.5} />
            </Sequence>
          ))}
        </Sequence>
      ))}
      <Audio src={staticFile("audio/pad.m4a")} loop volume={(f) => interpolate(f, [0, 30, INTRO_FRAMES - 45, INTRO_FRAMES], [0, 0.3, 0.3, 0], clamp)} />
    </AbsoluteFill>
  );
}
