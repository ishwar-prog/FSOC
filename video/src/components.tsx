import { createContext, useContext, type CSSProperties, type ReactNode } from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

import { color, font, shadow } from "./theme";

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

export type Hold = { at: number; frames: number };

export function remapFrame(frame: number, holds: Hold[]): number {
  let source = frame;
  for (const hold of holds) {
    if (source <= hold.at) break;
    if (source < hold.at + hold.frames) return hold.at;
    source -= hold.frames;
  }
  return source;
}

export function forwardFrame(source: number, holds: Hold[]): number {
  return source + holds.filter((hold) => hold.at < source).reduce((total, hold) => total + hold.frames, 0);
}

export const RealTime = createContext<{ frame: number; holds: Hold[] } | null>(null);

export function useRealTime() {
  const frame = useCurrentFrame();
  return useContext(RealTime) ?? { frame, holds: [] as Hold[] };
}

export function useSpring(delay = 0, damping = 18, mass = 0.8) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - delay, fps, config: { damping, mass, stiffness: 140 } });
}

export function useRise(delay = 0, distance = 24) {
  const progress = useSpring(delay, 22);
  return {
    opacity: Math.min(1, progress * 1.4),
    transform: `translateY(${(1 - progress) * distance}px)`,
    filter: `blur(${(1 - Math.min(1, progress)) * 6}px)`,
  } satisfies CSSProperties;
}

export function useFlyIn(delay = 0) {
  const progress = useSpring(delay, 16, 0.9);
  return {
    opacity: Math.min(1, progress * 1.6),
    transform: `perspective(1600px) translateY(${(1 - progress) * 90}px) rotateX(${(1 - progress) * 22}deg) rotateY(${(1 - progress) * -10}deg) scale(${0.94 + progress * 0.06})`,
    transformOrigin: "50% 100%",
  } satisfies CSSProperties;
}

export function Backdrop() {
  const frame = useCurrentFrame();
  const drift = frame * 0.35;
  const blobX = 50 + Math.sin(frame / 90) * 18;
  const blobY = 40 + Math.cos(frame / 110) * 12;
  return (
    <AbsoluteFill style={{ background: color.bg }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(900px 520px at ${blobX}% ${blobY}%, rgba(68,182,255,0.12), transparent 70%), radial-gradient(700px 420px at ${100 - blobX}% ${100 - blobY}%, rgba(8,180,77,0.05), transparent 70%)`,
        }}
      />
      <AbsoluteFill
        style={{
          backgroundImage: "radial-gradient(rgba(11,17,32,0.08) 1.2px, transparent 1.5px)",
          backgroundSize: "28px 28px",
          backgroundPosition: `${drift}px ${drift * 0.4}px`,
          maskImage: "radial-gradient(ellipse 75% 72% at 50% 45%, #000 20%, transparent 85%)",
          WebkitMaskImage: "radial-gradient(ellipse 75% 72% at 50% 45%, #000 20%, transparent 85%)",
        }}
      />
    </AbsoluteFill>
  );
}

export function Push({ children, amount = 0.035 }: { children: ReactNode; amount?: number }) {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const scale = interpolate(frame, [0, durationInFrames], [1, 1 + amount], { easing: Easing.inOut(Easing.sin) });
  return <AbsoluteFill style={{ transform: `scale(${scale})` }}>{children}</AbsoluteFill>;
}

export function Words({ text, delay = 0, size = 72, stagger = 3, style }: { text: string; delay?: number; size?: number; stagger?: number; style?: CSSProperties }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <h1
      style={{
        margin: 0,
        fontFamily: font.display,
        fontSize: size,
        fontWeight: 600,
        lineHeight: 1.08,
        letterSpacing: "-0.03em",
        color: color.text,
        ...style,
      }}
    >
      {text.split(" ").map((word, index) => {
        const progress = spring({ frame: frame - delay - index * stagger, fps, config: { damping: 20, mass: 0.7, stiffness: 160 } });
        return (
          <span key={`${word}-${index}`} style={{ display: "inline-block", overflow: "hidden", verticalAlign: "top", paddingBottom: "0.12em", marginBottom: "-0.12em" }}>
            <span
              style={{
                display: "inline-block",
                transform: `translateY(${(1 - progress) * 105}%) rotate(${(1 - progress) * 4}deg)`,
                filter: `blur(${(1 - Math.min(1, progress)) * 4}px)`,
                transformOrigin: "0 100%",
              }}
            >
              {word}
              {" "}
            </span>
          </span>
        );
      })}
    </h1>
  );
}

export function Note({ children, delay = 0, style }: { children: ReactNode; delay?: number; style?: CSSProperties }) {
  const rise = useRise(delay, 14);
  return (
    <p style={{ margin: 0, whiteSpace: "nowrap", fontFamily: font.mono, fontSize: 21, fontWeight: 500, letterSpacing: "0.01em", color: color.text3, ...rise, ...style }}>
      {children}
    </p>
  );
}

export function Split({ text, visual, textWidth = 640 }: { text: ReactNode; visual: ReactNode; textWidth?: number }) {
  return (
    <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 140px", gap: 100 }}>
      <div style={{ width: textWidth, display: "flex", flexDirection: "column", gap: 30 }}>{text}</div>
      <div style={{ flex: 1, display: "flex", justifyContent: "center" }}>{visual}</div>
    </AbsoluteFill>
  );
}

export function Card({ children, width, style }: { children: ReactNode; width?: number; style?: CSSProperties }) {
  return (
    <div style={{ position: "relative", width, borderRadius: 22, background: color.surface, border: `1px solid ${color.line}`, boxShadow: shadow, overflow: "hidden", ...style }}>
      {children}
    </div>
  );
}

export function Sheen({ at, duration = 26 }: { at: number; duration?: number }) {
  const frame = useCurrentFrame();
  const x = interpolate(frame, [at, at + duration], [-40, 140], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  if (frame < at || frame > at + duration) return null;
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        background: `linear-gradient(105deg, transparent ${x - 18}%, rgba(255,255,255,0.75) ${x}%, transparent ${x + 18}%)`,
        mixBlendMode: "screen",
      }}
    />
  );
}

export function Burst({ at, size = 30, tone = color.ok }: { at: number; size?: number; tone?: string }) {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [at, at + 16], [0, 1], clamp);
  if (frame < at || t >= 1) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        width: size,
        height: size,
        marginLeft: -size / 2,
        marginTop: -size / 2,
        borderRadius: "50%",
        border: `2px solid ${tone}`,
        transform: `scale(${1 + t * 1.6})`,
        opacity: 1 - t,
        pointerEvents: "none",
      }}
    />
  );
}

export function Check({ size = 30, progress = 1, tone = color.ok }: { size?: number; progress?: number; tone?: string }) {
  const pop = 0.6 + Math.min(1, progress) * 0.4 + Math.sin(Math.min(1, progress) * Math.PI) * 0.18;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ transform: `scale(${pop})` }}>
      <circle cx="12" cy="12" r="11" fill={tone} opacity={Math.min(1, progress * 2)} />
      <polyline
        points="7 12.5 10.5 16 17 9"
        fill="none"
        stroke="#fff"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray="16"
        strokeDashoffset={16 * (1 - progress)}
      />
    </svg>
  );
}

export function Counter({ from, to, start, end, format }: { from: number; to: number; start: number; end: number; format: (value: number) => string }) {
  const frame = useCurrentFrame();
  const value = interpolate(frame, [start, end], [from, to], { ...clamp, easing: (t) => (1 - 2 ** (-10 * t)) / (1 - 2 ** -10) });
  return <>{format(value)}</>;
}
