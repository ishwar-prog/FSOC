import type { ReactNode } from "react";
import { AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig } from "remotion";

import { Backdrop, Card, Counter, Note, Push, Words, clamp, useFlyIn, useRise } from "./components";
import { Brackets, Mark, Night, Pass, Sky, StatePill, Trace, Wordmark, type Light, starField } from "./fsoc";
import { TerminalGlyph } from "./stills/Stills";
import { BENCH, HAZARDS, STATE_COLOR, TARGETS, TERMINALS, color, font } from "./theme";
import hover from "../public/data/hover.json";

// One component per scene, one idea each. Scene order and durations live in Intro.tsx.

type Frame = { t: number; state: string; err: number | null; track: [number, number] | null; p: number };
const HOVER = (hover as { frames: Frame[] }).frames;
const HOVER_ERR = (hover as unknown as { metrics: { tracking_error: { value: number } } }).metrics.tracking_error.value;

function Headline({ children, delay = 0, size = 78, light = false }: { children: string; delay?: number; size?: number; light?: boolean }) {
  return <Words text={children} delay={delay} size={size} style={{ color: light ? "#f3f6fb" : color.text }} />;
}

function Kicker({ children, delay = 0, tone = color.accentInk }: { children: ReactNode; delay?: number; tone?: string }) {
  const rise = useRise(delay, 12);
  return <div style={{ fontFamily: font.mono, fontSize: 24, fontWeight: 700, letterSpacing: "0.14em", textTransform: "uppercase", color: tone, ...rise }}>{children}</div>;
}

// ---------- 1. the link: two terminals, one very narrow beam, and it slips off

export function LinkScene() {
  const frame = useCurrentFrame();
  const drift = interpolate(frame, [52, 76], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const bob = Math.sin(frame / 9) * 6;
  const A = { x: 360, y: 700 };
  const B = { x: 1480, y: 330 + bob };
  const aimY = B.y + drift * 120;
  const link = interpolate(frame, [52, 72], [100, 0], clamp);
  const rise = useFlyIn(4);
  return (
    <AbsoluteFill>
      <Backdrop />
      <Push>
        <AbsoluteFill style={{ padding: "110px 140px", gap: 20 }}>
          <Kicker delay={2}>Free-space optical link</Kicker>
          <Headline delay={6}>Before any data flows, the beam has to hit.</Headline>
        </AbsoluteFill>
        <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, ...rise }}>
          <defs>
            <linearGradient id="beam" x1="0" x2="1">
              <stop offset="0" stopColor={color.accent} stopOpacity="0.9" />
              <stop offset="1" stopColor={color.accent} stopOpacity="0.25" />
            </linearGradient>
          </defs>
          {/* ground mast */}
          <path d={`M${A.x} 900V${A.y}`} stroke={color.text} strokeWidth="6" />
          <path d={`M${A.x - 70} 900h140`} stroke={color.text} strokeWidth="6" strokeLinecap="round" />
          <rect x={A.x - 26} y={A.y - 22} width="52" height="44" rx="8" fill={color.text} />
          {/* beam */}
          <line x1={A.x + 26} y1={A.y} x2={B.x - 40} y2={aimY} stroke="url(#beam)" strokeWidth={4} strokeLinecap="round" />
          {/* drone */}
          <g transform={`translate(${B.x - 60} ${B.y - 60}) scale(2.5)`}>
            <TerminalGlyphPath />
          </g>
          {drift > 0.5 && <circle cx={B.x - 40} cy={aimY} r={10 + drift * 6} fill="none" stroke={color.bad} strokeWidth="3" opacity={drift} />}
        </svg>
        <div style={{ position: "absolute", right: 140, bottom: 110, width: 520 }}>
          <Note delay={30}>link margin</Note>
          <div style={{ marginTop: 14, height: 14, borderRadius: 999, background: color.line, overflow: "hidden" }}>
            <div style={{ width: `${link}%`, height: "100%", background: link > 50 ? color.ok : color.bad, borderRadius: 999 }} />
          </div>
          <div style={{ marginTop: 14, fontFamily: font.mono, fontSize: 30, fontWeight: 700, color: link > 50 ? color.ok : color.bad, opacity: interpolate(frame, [30, 40], [0, 1], clamp) }}>
            {link > 50 ? "LINK UP" : "LINK LOST · 0 bits"}
          </div>
        </div>
      </Push>
    </AbsoluteFill>
  );
}

function TerminalGlyphPath() {
  const s = { fill: "none", stroke: color.text, strokeWidth: 2.4, strokeLinecap: "round" as const };
  return (
    <g {...s}>
      <circle cx="10" cy="10" r="6" />
      <circle cx="38" cy="10" r="6" />
      <circle cx="10" cy="38" r="6" />
      <circle cx="38" cy="38" r="6" />
      <path d="M14 14l20 20M34 14L14 34" />
      <rect x="19" y="19" width="10" height="10" rx="2" fill={color.text} />
    </g>
  );
}

// ---------- 2. the mark

export function LogoScene() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 13, stiffness: 150 } });
  const draw = interpolate(frame, [0, 26], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return (
    <Night>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 34 }}>
        <div style={{ transform: `scale(${0.6 + pop * 0.4})` }}>
          <Mark size={160} draw={draw} locked={frame > 30 ? 1 : 0} />
        </div>
        <Wordmark size={150} delay={10} tone="#f3f6fb" />
      </AbsoluteFill>
    </Night>
  );
}

// ---------- 3. the sky: a 4° × 3° view, and the beacon is the dimmest thing in it

const SKY_W = 1240;
const SKY_H = 700;
const SKY_NAMED: (Light & { label: string; tone: string })[] = [
  { id: "sat", kind: "sat", x: 230, y: 170, size: 10, peak: 1, vx: 0.5, label: "satellite · steady", tone: "#fff3d6" },
  { id: "lamp", kind: "lamp", x: 230, y: 560, size: 11, peak: 1, label: "street lamp · steady", tone: "#ffd59a" },
  { id: "tower", kind: "tower", x: 1000, y: 150, size: 9, peak: 1, hz: 0.5, label: "tower · 0.5 Hz", tone: "#ff8a7a" },
  { id: "strobe", kind: "strobe", x: 900, y: 560, size: 9, peak: 1, label: "strobe", tone: "#ffffff" },
  { id: "decoy", kind: "decoy", x: 960, y: 420, size: 9, peak: 0.95, hz: 3, label: "rival laser · 3 Hz", tone: "#ffc27a" },
  { id: "beacon", kind: "beacon", x: 620, y: 350, size: 6, peak: 0.7, hz: 5, label: "beacon · 5 Hz", tone: "#8fd6ff" },
];
const SKY_LIGHTS: Light[] = [...starField("intro-sky", 140, SKY_W, SKY_H), ...SKY_NAMED];

export function SkyScene() {
  const frame = useCurrentFrame();
  const card = useFlyIn(6);
  const reveal = (i: number) => interpolate(frame, [40 + i * 12, 52 + i * 12], [0, 1], clamp);
  const hunt = interpolate(frame, [130, 150], [0, 1], clamp);
  return (
    <AbsoluteFill>
      <Backdrop />
      <AbsoluteFill style={{ padding: "90px 140px", gap: 16 }}>
        <Kicker>The camera's 4° × 3° view</Kicker>
        <Headline delay={4} size={70}>The beacon is rarely the brightest light.</Headline>
      </AbsoluteFill>
      <div style={{ position: "absolute", left: (1920 - SKY_W) / 2, top: 300, borderRadius: 26, overflow: "hidden", boxShadow: "0 40px 90px -40px rgba(11,17,32,0.6)", ...card }}>
        <Sky lights={SKY_LIGHTS} frame={frame} width={SKY_W} height={SKY_H} noise={0.05} />
        {SKY_NAMED.map((light, i) => (
          <div key={light.id} style={{ position: "absolute", left: light.x + (light.vx ?? 0) * frame + 22, top: light.y - 40, opacity: reveal(i), fontFamily: font.mono, fontSize: 21, fontWeight: 600, color: light.tone, whiteSpace: "nowrap", textShadow: "0 1px 8px #000" }}>
            {light.label}
          </div>
        ))}
        {hunt > 0 && <Brackets x={620} y={350} size={56} progress={hunt} tone={color.accent} spin={(1 - hunt) * 45} />}
      </div>
    </AbsoluteFill>
  );
}

// ---------- 4. the blink. Beacon rate and P from the decoys case (fsoc identity output); clutter rows illustrative

const ROWS = [
  { light: SKY_NAMED[5], rate: "5.16 Hz", p: 1.0 },
  { light: SKY_NAMED[4], rate: "3.00 Hz", p: 0.09 },
  { light: SKY_NAMED[2], rate: "0.50 Hz", p: 0.02 },
  { light: SKY_NAMED[3], rate: "0.75 Hz", p: 0.05 },
  { light: SKY_NAMED[1], rate: "steady", p: 0.0 },
];

export function BlinkScene() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill>
      <Backdrop />
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 140px", gap: 90 }}>
        <div style={{ width: 620, display: "flex", flexDirection: "column", gap: 28 }}>
          <Kicker>Beacon identification</Kicker>
          <Headline delay={4} size={74}>It learns how the beacon blinks.</Headline>
          <Note delay={30} style={{ whiteSpace: "normal", lineHeight: 1.5 }}>tracklets · forced photometry · FFT · naive-Bayes beacon vs clutter</Note>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 16 }}>
          {ROWS.map((row, i) => {
            const fly = spring({ frame: frame - 10 - i * 6, fps, config: { damping: 18, stiffness: 140 } });
            const bar = interpolate(frame, [60 + i * 4, 130], [0.5, row.p], { ...clamp, easing: Easing.inOut(Easing.cubic) });
            const beacon = i === 0;
            const won = beacon && frame > 130;
            const tone = beacon ? (won ? color.ok : color.accentInk) : color.text3;
            return (
              <Card key={row.light.id} style={{ padding: "18px 26px", display: "flex", alignItems: "center", gap: 26, opacity: fly, transform: `translateX(${(1 - fly) * 120}px)`, border: won ? `2px solid ${color.ok}` : undefined }}>
                <div style={{ width: 210, fontFamily: font.mono, fontSize: 21, fontWeight: 600, color: beacon ? color.text : color.text2 }}>{row.light.label.split(" · ")[0]}</div>
                <div style={{ padding: "4px 10px", borderRadius: 10, background: beacon ? color.night : "#1a2233" }}>
                  <Trace light={row.light} frame={frame} width={230} height={40} samples={48} tone={beacon ? (won ? color.ok : "#8fd6ff") : "#aab4c8"} />
                </div>
                <div style={{ width: 110, fontFamily: font.mono, fontSize: 22, color: color.text2 }}>{row.rate}</div>
                <div style={{ flex: 1, height: 12, borderRadius: 999, background: color.line, overflow: "hidden" }}>
                  <div style={{ width: `${bar * 100}%`, height: "100%", borderRadius: 999, background: tone }} />
                </div>
                <div style={{ width: 90, textAlign: "right", fontFamily: font.mono, fontSize: 26, fontWeight: 700, color: tone }}>{bar.toFixed(2)}</div>
              </Card>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

// ---------- 5. the lock: replayed from the real Drone · Hover Hold run (video/public/data/hover.json)

const LOCK_LIGHTS: Light[] = [...starField("lock", 110, 960, 720), { id: "beacon", kind: "beacon", x: 0, y: 0, size: 7, peak: 0.8, hz: 5 }];

export function LockScene() {
  const frame = useCurrentFrame();
  const card = useFlyIn(0);
  const index = Math.max(0, Math.min(HOVER.length - 1, frame - 16));
  const now = HOVER[index];
  const lockIndex = HOVER.findIndex((f) => f.state === "LOCKED");
  const lockT = HOVER[lockIndex].t;
  const scale = 960 / 640;
  // beacon sits at the true bore-sight centre; the track comes from the tracker
  const bx = 480;
  const by = 360;
  const trackAt = now.track ? { x: now.track[0] * scale, y: now.track[1] * scale } : null;
  const lights = LOCK_LIGHTS.map((l) => (l.kind === "beacon" ? { ...l, x: bx, y: by } : l));
  const locked = now.state === "LOCKED";
  return (
    <AbsoluteFill>
      <Backdrop />
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 130px", gap: 80 }}>
        <div style={{ borderRadius: 26, overflow: "hidden", position: "relative", boxShadow: "0 40px 90px -40px rgba(11,17,32,0.6)", ...card }}>
          <Sky lights={lights} frame={frame} width={960} height={720} />
          {!locked && now.state !== "SEARCH" && (
            <Brackets x={bx + Math.sin(frame) * 14} y={by + Math.cos(frame * 1.3) * 14} size={90} tone={STATE_COLOR.ACQUIRING} weight={3} />
          )}
          {locked && trackAt && <Brackets x={bx + (trackAt.x - 320 * scale)} y={by + (trackAt.y - 240 * scale)} size={64} tone={color.ok} weight={4} />}
          {locked && <div style={{ position: "absolute", left: bx - 15, top: by - 15, width: 30, height: 30, borderRadius: "50%", border: `1.5px dashed ${color.ok}` }} />}
          <div style={{ position: "absolute", left: 24, top: 22 }}>
            <StatePill state={now.state} size={22} />
          </div>
          <div style={{ position: "absolute", right: 24, bottom: 20, fontFamily: font.mono, fontSize: 20, color: "#7f8aa3" }}>Drone · Hover Hold · seed 42</div>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 34 }}>
          <Kicker>Search → acquire → lock</Kicker>
          <Readout label="since cold start" value={`${now.t.toFixed(2)} s`} tone={color.text} />
          <Readout label="acquisition" value={locked || index > lockIndex ? `${lockT.toFixed(2)} s` : "…"} tone={locked ? color.ok : color.text3} />
          <Readout label="tracking error" value={locked ? `${HOVER_ERR.toFixed(2)} px` : "—"} tone={locked ? color.ok : color.text3} />
          <Readout label="beacon probability" value={now.p.toFixed(2)} tone={now.p > 0.9 ? color.ok : color.text3} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

function Readout({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontFamily: font.mono, fontSize: 22, color: color.text3 }}>{label}</span>
      <span style={{ fontFamily: font.display, fontSize: 72, fontWeight: 600, letterSpacing: "-0.03em", color: tone, fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}

// ---------- 6. six terminals, one tracking core

export function TerminalsScene() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill>
      <Backdrop />
      <AbsoluteFill style={{ padding: "100px 120px", gap: 16 }}>
        <Kicker>Any terminal</Kicker>
        <Headline delay={4} size={70}>Drone to space station. Same code.</Headline>
      </AbsoluteFill>
      <div style={{ position: "absolute", left: 120, right: 120, top: 380, display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 24, perspective: 1600 }}>
        {TERMINALS.map((terminal, i) => {
          const p = spring({ frame: frame - 14 - i * 5, fps, config: { damping: 16, mass: 0.9, stiffness: 130 } });
          return (
            <Card key={terminal.name} style={{ padding: "36px 18px", display: "flex", flexDirection: "column", alignItems: "center", gap: 14, textAlign: "center", opacity: Math.min(1, p * 1.6), transform: `translateY(${(1 - p) * 140}px) rotateX(${(1 - p) * 40}deg)` }}>
              <div style={{ width: 130, height: 130, borderRadius: 32, background: i >= 3 ? color.night : color.accentSoft, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <TerminalGlyph index={i} size={80} tone={i >= 3 ? color.accent : color.accentInk} />
              </div>
              <div style={{ fontFamily: font.display, fontWeight: 600, fontSize: 30 }}>{terminal.name}</div>
              <div style={{ fontFamily: font.mono, fontSize: 36, fontWeight: 700, color: color.ok }}>{terminal.acq}</div>
              <div style={{ fontFamily: font.mono, fontSize: 17, color: color.text3 }}>to lock</div>
            </Card>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 120, bottom: 90 }}>
        <Note delay={60}>+ satellite-to-satellite crosslinks · manual drive · vehicle and ship-deck mounts</Note>
      </div>
    </AbsoluteFill>
  );
}

// ---------- 7. hazards stack up, the lock holds

const HZ_LIGHTS: Light[] = [...starField("hz", 120, 1100, 640), { id: "beacon", kind: "beacon", x: 550, y: 320, size: 7, peak: 0.85, hz: 5 }, { id: "lamp", kind: "lamp", x: 180, y: 520, size: 10, peak: 1 }, { id: "decoy", kind: "decoy", x: 900, y: 180, size: 8, peak: 0.9, hz: 3 }];

export function HazardsScene() {
  const frame = useCurrentFrame();
  const on = (i: number) => interpolate(frame, [16 + i * 12, 26 + i * 12], [0, 1], clamp);
  const [fog, rain, shimmer, noise, vib, glare, occ] = [0, 1, 2, 3, 4, 5, 6].map(on);
  const shakeX = vib * (random(`vx${frame}`) - 0.5) * 10;
  const shakeY = vib * (random(`vy${frame}`) - 0.5) * 10;
  const occX = interpolate(frame, [95, 125], [-200, 1300], clamp);
  const done = frame > 118;
  return (
    <AbsoluteFill>
      <Backdrop />
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 120px", gap: 70 }}>
        <div style={{ position: "relative", width: 1100, height: 640, borderRadius: 26, overflow: "hidden", boxShadow: "0 40px 90px -40px rgba(11,17,32,0.6)" }}>
          <div style={{ transform: `translate(${shakeX}px, ${shakeY}px)`, filter: `blur(${shimmer * 1.2}px)` }}>
            <Sky lights={HZ_LIGHTS} frame={frame} width={1100} height={640} noise={0.05 + noise * 0.18} />
          </div>
          <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(200,210,225,0.55), rgba(160,170,190,0.35))", opacity: fog * 0.7 }} />
          <AbsoluteFill style={{ opacity: rain * 0.5, backgroundImage: "repeating-linear-gradient(105deg, rgba(200,220,255,0.35) 0 1px, transparent 1px 22px)", backgroundPosition: `${frame * 6}px ${frame * 30}px` }} />
          <AbsoluteFill style={{ background: "radial-gradient(circle at 92% 8%, rgba(255,240,200,0.85), transparent 45%)", opacity: glare }} />
          {occ > 0 && <div style={{ position: "absolute", left: occX, top: 250, width: 180, height: 120, borderRadius: "50%", background: "rgba(8,10,16,0.92)", filter: "blur(10px)" }} />}
          <Brackets x={550 + shakeX} y={320 + shakeY} size={58} tone={frame > 102 && frame < 116 ? STATE_COLOR.COASTING : color.ok} weight={4} />
          <div style={{ position: "absolute", left: 24, top: 22 }}>
            <StatePill state={frame > 102 && frame < 116 ? "COASTING" : "LOCKED"} size={22} />
          </div>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 14 }}>
          <Kicker>Eight hazards, stacked</Kicker>
          {HAZARDS.map((name, i) => {
            const p = i < 7 ? on(i) : on(3);
            return (
              <div key={name} style={{ display: "flex", alignItems: "center", gap: 14, fontFamily: font.text, fontSize: 30, fontWeight: 500, color: color.text, opacity: 0.25 + p * 0.75 }}>
                <span style={{ width: 14, height: 14, borderRadius: 4, background: p > 0.5 ? color.warn : color.line }} />
                {name}
              </div>
            );
          })}
          <div style={{ marginTop: 18, display: "flex", alignItems: "center", gap: 16, fontFamily: font.mono, fontSize: 24, fontWeight: 600, color: color.text2, opacity: done ? 1 : 0 }}>
            Storm · 1.60 s · 2.19 px <Pass size={20} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

// ---------- 8. proof: python benchmark.py

export function ProofScene() {
  const frame = useCurrentFrame();
  const typed = "python benchmark.py".slice(0, Math.max(0, Math.floor((frame - 6) / 1.5)));
  const card = useFlyIn(0);
  return (
    <AbsoluteFill>
      <Backdrop />
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 60 }}>
        <div style={{ width: 1060, height: 640, borderRadius: 22, background: color.night, boxShadow: "0 40px 90px -40px rgba(11,17,32,0.6)", padding: "30px 36px", fontFamily: font.mono, fontSize: 21, color: "#c9d2e3", overflow: "hidden", ...card }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 22 }}>
            {["#ff5f57", "#febc2e", "#28c840"].map((c) => <span key={c} style={{ width: 13, height: 13, borderRadius: "50%", background: c }} />)}
          </div>
          <div style={{ color: "#fff" }}>
            <span style={{ color: color.accent }}>›</span> {typed}
            <span style={{ opacity: frame % 20 < 10 ? 1 : 0 }}>▍</span>
          </div>
          <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 9 }}>
            {BENCH.map((row, i) => {
              const at = 40 + i * 5;
              if (frame < at) return null;
              return (
                <div key={row[0]} style={{ display: "flex", gap: 18, opacity: interpolate(frame, [at, at + 4], [0, 1], clamp) }}>
                  <span style={{ width: 470, whiteSpace: "nowrap", overflow: "hidden" }}>{row[0]}</span>
                  <span style={{ width: 90 }}>{row[1]}</span>
                  <span style={{ width: 100 }}>{row[2]}</span>
                  <span style={{ width: 90 }}>{row[3]}</span>
                  <span style={{ color: color.ok, fontWeight: 700 }}>PASS</span>
                </div>
              );
            })}
            {frame > 104 && <div style={{ color: "#7f8aa3" }}>… 16 more</div>}
            {frame > 110 && <div style={{ marginTop: 8, color: color.ok, fontWeight: 700 }}>28 of 28 cases pass all six targets</div>}
          </div>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 22 }}>
          <div style={{ fontFamily: font.display, fontSize: 150, fontWeight: 600, letterSpacing: "-0.04em", color: color.ok, lineHeight: 1 }}>
            <Counter from={0} to={28} start={40} end={112} format={(v) => `${Math.round(v)}`} />
            <span style={{ color: color.text3, fontSize: 90 }}> / 28</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {TARGETS.map((target, i) => {
              const p = interpolate(frame, [70 + i * 6, 80 + i * 6], [0, 1], clamp);
              return (
                <Card key={target.label} style={{ padding: "14px 18px", opacity: p, transform: `scale(${0.9 + p * 0.1})` }}>
                  <div style={{ fontFamily: font.text, fontSize: 18, color: color.text3 }}>{target.label} {target.target}</div>
                  <div style={{ fontFamily: font.mono, fontSize: 30, fontWeight: 700, color: color.ok }}>{target.value}</div>
                </Card>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

// ---------- 9. close

export function CloseScene() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame: frame - 4, fps, config: { damping: 13, stiffness: 150 } });
  const draw = interpolate(frame, [4, 28], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const tag = interpolate(frame, [40, 52], [0, 1], clamp);
  return (
    <Night>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 32 }}>
        <div style={{ transform: `scale(${0.6 + pop * 0.4})` }}>
          <Mark size={150} draw={draw} locked={frame > 30 ? 1 : 0} />
        </div>
        <Wordmark size={140} delay={12} tone="#f3f6fb" />
        <div style={{ fontFamily: font.mono, fontSize: 30, fontWeight: 600, letterSpacing: "0.2em", color: color.accent, opacity: tag }}>POINT · ACQUIRE · TRACK</div>
        <div style={{ marginTop: 20, fontFamily: font.mono, fontSize: 24, color: "#7f8aa3", opacity: tag }}>github.com/ishwar-prog/FSOC · SIH26169</div>
      </AbsoluteFill>
    </Night>
  );
}

