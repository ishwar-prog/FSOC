import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, interpolate, random, spring, useCurrentFrame, useVideoConfig } from "remotion";

import { clamp } from "./components";
import { STATE_COLOR, color, font } from "./theme";

// ---------- the sky: every light either stays steady or blinks at the wrong rhythm, except one

export type LightKind = "star" | "lamp" | "tower" | "strobe" | "decoy" | "beacon" | "sat";
export type Light = { id: string; kind: LightKind; x: number; y: number; size: number; peak: number; hz?: number; vx?: number; label?: string };

// Brightness 0..1 at a frame. The beacon is a 5 Hz square wave: 3 frames on, 3 off at 30 fps.
export function lightLevel(light: Light, frame: number): number {
  const t = frame / 30;
  switch (light.kind) {
    case "star":
      return light.peak * (0.9 + 0.1 * Math.sin(frame * 0.7 + light.x));
    case "lamp":
      return light.peak;
    case "tower":
      return light.peak * (0.35 + 0.65 * (0.5 + 0.5 * Math.sin(2 * Math.PI * (light.hz ?? 0.5) * t)));
    case "strobe":
      return light.peak * ((frame + Math.round(light.x)) % 40 < 3 ? 1 : 0.04);
    case "decoy":
    case "beacon": {
      const period = 30 / (light.hz ?? 5);
      return light.peak * ((frame % period) < period / 2 ? 1 : 0.06);
    }
    case "sat":
      return light.peak;
  }
}

export function lightPos(light: Light, frame: number) {
  return { x: light.x + (light.vx ?? 0) * frame, y: light.y };
}

export function starField(seed: string, count: number, width: number, height: number): Light[] {
  return new Array(count).fill(0).map((_, i) => ({
    id: `${seed}-${i}`,
    kind: "star" as const,
    x: random(`${seed}x${i}`) * width,
    y: random(`${seed}y${i}`) * height,
    size: 1.4 + random(`${seed}s${i}`) * 2.2,
    peak: 0.25 + random(`${seed}p${i}`) ** 3 * 0.75,
  }));
}

export function Glow({ x, y, size, level, tint = "#ffffff", halo = 5 }: { x: number; y: number; size: number; level: number; tint?: string; halo?: number }) {
  const s = size * (0.6 + level * 0.8);
  return (
    <div style={{ position: "absolute", left: x, top: y, width: 0, height: 0 }}>
      <div
        style={{
          position: "absolute",
          left: -s * halo,
          top: -s * halo,
          width: s * halo * 2,
          height: s * halo * 2,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${tint} 0%, ${tint}55 ${100 / halo / 1.4}%, transparent 60%)`,
          opacity: Math.min(1, level * 1.1),
        }}
      />
      <div style={{ position: "absolute", left: -s / 2, top: -s / 2, width: s, height: s, borderRadius: "50%", background: "#fff", opacity: Math.min(1, level * 1.4) }} />
    </div>
  );
}

const TINT: Record<LightKind, string> = {
  star: "#dfe8ff",
  lamp: "#ffd59a",
  tower: "#ff8a7a",
  strobe: "#ffffff",
  decoy: "#ffc27a",
  beacon: "#8fd6ff",
  sat: "#fff3d6",
};

export function Sky({ lights, frame, width, height, noise = 0.05, style }: { lights: Light[]; frame: number; width: number; height: number; noise?: number; style?: CSSProperties }) {
  return (
    <div style={{ position: "relative", width, height, overflow: "hidden", background: `radial-gradient(ellipse at 50% 40%, ${color.night2}, ${color.night} 75%)`, ...style }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: noise,
          backgroundImage: `radial-gradient(rgba(255,255,255,0.9) 0.6px, transparent 0.8px)`,
          backgroundSize: `${5 + (frame % 3)}px ${6 + (frame % 2)}px`,
        }}
      />
      {lights.map((light) => {
        const p = lightPos(light, frame);
        return <Glow key={light.id} x={p.x} y={p.y} size={light.size} level={lightLevel(light, frame)} tint={TINT[light.kind]} halo={light.kind === "star" ? 3 : 5} />;
      })}
    </div>
  );
}

// ---------- lock brackets (ui/camera_view.py): four corners that spring in and take the state colour

export function Brackets({ x, y, size, progress = 1, tone = color.ok, weight = 3, spin = 0 }: { x: number; y: number; size: number; progress?: number; tone?: string; weight?: number; spin?: number }) {
  const open = size * (1 + (1 - progress) * 1.6);
  const arm = size * 0.32;
  const corner = (sx: number, sy: number) => (
    <div
      key={`${sx}${sy}`}
      style={{
        position: "absolute",
        left: (sx * open) / 2 - (sx > 0 ? arm : 0),
        top: (sy * open) / 2 - (sy > 0 ? arm : 0),
        width: arm,
        height: arm,
        borderColor: tone,
        borderStyle: "solid",
        borderWidth: 0,
        [sy < 0 ? "borderTopWidth" : "borderBottomWidth"]: weight,
        [sx < 0 ? "borderLeftWidth" : "borderRightWidth"]: weight,
        borderRadius: 3,
      }}
    />
  );
  return (
    <div style={{ position: "absolute", left: x, top: y, width: 0, height: 0, opacity: Math.min(1, progress * 2), transform: `rotate(${spin}deg)` }}>
      {[-1, 1].flatMap((sx) => [-1, 1].map((sy) => corner(sx, sy)))}
    </div>
  );
}

// ---------- brightness trace: the history the identifier Fourier-analyses

export function Trace({ light, frame, width = 180, height = 40, samples = 60, tone = "#8fd6ff", strokeWidth = 2 }: { light: Light; frame: number; width?: number; height?: number; samples?: number; tone?: string; strokeWidth?: number }) {
  const points = new Array(samples).fill(0).map((_, i) => {
    const f = frame - (samples - 1 - i);
    const v = f < 0 ? 0 : lightLevel(light, f) / Math.max(0.01, light.peak);
    return `${(i / (samples - 1)) * width},${height - 2 - v * (height - 4)}`;
  });
  return (
    <svg width={width} height={height} style={{ display: "block", overflow: "visible" }}>
      <polyline points={points.join(" ")} fill="none" stroke={tone} strokeWidth={strokeWidth} strokeLinejoin="round" />
    </svg>
  );
}

// ---------- state band: SEARCH -> ACQUIRING -> LOCKED

export function StatePill({ state, size = 22 }: { state: string; size?: number }) {
  const tone = STATE_COLOR[state] ?? color.text3;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: size * 0.45,
        padding: `${size * 0.35}px ${size * 0.8}px`,
        borderRadius: 999,
        background: `${tone}22`,
        color: tone,
        fontFamily: font.mono,
        fontWeight: 700,
        fontSize: size,
        letterSpacing: "0.06em",
      }}
    >
      <span style={{ width: size * 0.45, height: size * 0.45, borderRadius: "50%", background: tone }} />
      {state}
    </span>
  );
}

// ---------- the mark: an ink tile, four lock corners, a beacon dot

export function Mark({ size, draw = 1, locked = 1 }: { size: number; draw?: number; locked?: number }) {
  const part = (from: number, to: number) => interpolate(draw, [from, to], [0, 1], clamp);
  const c = part(0, 0.6);
  const d = 7 + (1 - c) * 6;
  const arm = 5;
  const dot = part(0.55, 0.85);
  const tone = locked >= 1 ? color.ok : color.accent;
  const corners = [
    `M${16 - d} ${16 - d + arm}V${16 - d}H${16 - d + arm}`,
    `M${16 + d - arm} ${16 - d}H${16 + d}V${16 - d + arm}`,
    `M${16 + d} ${16 + d - arm}V${16 + d}H${16 + d - arm}`,
    `M${16 - d + arm} ${16 + d}H${16 - d}V${16 + d - arm}`,
  ];
  return (
    <svg width={size} height={size} viewBox="0 0 32 32">
      <defs>
        <linearGradient id="fsoc-tile" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#18253c" />
          <stop offset="1" stopColor="#0b1120" />
        </linearGradient>
        <radialGradient id="fsoc-dot">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.35" stopColor={color.accent} />
          <stop offset="1" stopColor={color.accent} stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" fill="url(#fsoc-tile)" stroke="#2c3a52" />
      <circle cx="16" cy="16" r={6 * dot} fill="url(#fsoc-dot)" />
      <circle cx="16" cy="16" r={1.6 * dot} fill="#fff" />
      {corners.map((path) => (
        <path key={path} d={path} fill="none" stroke={tone} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity={c} />
      ))}
    </svg>
  );
}

export function Wordmark({ size = 64, delay = 0, tone = color.text }: { size?: number; delay?: number; tone?: string }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const text = "FSOC Beacon Tracker";
  return (
    <div style={{ fontFamily: font.display, fontWeight: 600, fontSize: size, letterSpacing: "-0.03em", color: tone, whiteSpace: "nowrap" }}>
      {text.split("").map((ch, i) => {
        const p = spring({ frame: frame - delay - i * 1.2, fps, config: { damping: 20, stiffness: 180 } });
        return (
          <span key={i} style={{ display: "inline-block", opacity: p, transform: `translateY(${(1 - p) * 0.4}em)`, filter: `blur(${(1 - p) * 6}px)`, whiteSpace: "pre" }}>
            {ch}
          </span>
        );
      })}
    </div>
  );
}

export function Pass({ size = 18 }: { size?: number }) {
  return (
    <span style={{ padding: `${size * 0.2}px ${size * 0.6}px`, borderRadius: 999, background: color.okSoft, color: color.ok, fontFamily: font.mono, fontWeight: 700, fontSize: size, letterSpacing: "0.06em" }}>
      PASS
    </span>
  );
}

export function Night({ children }: { children: ReactNode }) {
  return <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 40%, ${color.night2}, ${color.night} 80%)` }}>{children}</AbsoluteFill>;
}
