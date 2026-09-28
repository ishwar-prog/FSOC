import type { ReactNode } from "react";
import { AbsoluteFill } from "remotion";

import { Mark, Sky, Brackets, type Light, starField } from "../fsoc";
import { HAZARDS, TERMINALS, color, font, shadow } from "../theme";

// README images. Each is a single-frame composition rendered with `remotion still`.

const BEACON_FRAME = 1; // an ON phase of the 5 Hz beacon

function Page({ children, pad = 80 }: { children: ReactNode; pad?: number }) {
  return (
    <AbsoluteFill style={{ background: color.bg, padding: pad, fontFamily: font.text, color: color.text }}>
      <AbsoluteFill
        style={{
          backgroundImage: "radial-gradient(rgba(11,17,32,0.07) 1.2px, transparent 1.5px)",
          backgroundSize: "28px 28px",
          maskImage: "radial-gradient(ellipse 80% 80% at 50% 50%, #000 30%, transparent 90%)",
          WebkitMaskImage: "radial-gradient(ellipse 80% 80% at 50% 50%, #000 30%, transparent 90%)",
        }}
      />
      <div style={{ position: "relative", width: "100%", height: "100%" }}>{children}</div>
    </AbsoluteFill>
  );
}

function Tile({ children, dark = false, style }: { children: ReactNode; dark?: boolean; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        borderRadius: 24,
        background: dark ? color.night : color.surface,
        border: `1px solid ${dark ? "#26324a" : color.line}`,
        boxShadow: shadow,
        overflow: "hidden",
        position: "relative",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ---------- Banner 1920×560

const BANNER_LIGHTS: Light[] = [
  ...starField("banner", 90, 820, 480),
  { id: "lamp", kind: "lamp", x: 170, y: 380, size: 7, peak: 1 },
  { id: "lamp2", kind: "lamp", x: 250, y: 395, size: 6, peak: 0.9 },
  { id: "tower", kind: "tower", x: 640, y: 120, size: 6, peak: 1, hz: 0.5 },
  { id: "sat", kind: "sat", x: 120, y: 110, size: 7, peak: 1 },
  { id: "decoy", kind: "decoy", x: 690, y: 330, size: 6, peak: 0.9, hz: 3 },
  { id: "beacon", kind: "beacon", x: 430, y: 235, size: 5, peak: 0.8, hz: 5 },
];

export function Banner() {
  return (
    <Page pad={40}>
      <div style={{ display: "flex", alignItems: "center", height: "100%", gap: 70, paddingLeft: 60 }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 26 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 26 }}>
            <Mark size={104} />
            <div style={{ fontFamily: font.display, fontWeight: 600, fontSize: 76, letterSpacing: "-0.035em", whiteSpace: "nowrap" }}>FSOC Beacon Tracker</div>
          </div>
          <div style={{ fontSize: 38, lineHeight: 1.3, color: color.text2, maxWidth: 860 }}>
            Finds the partner terminal's beacon <b style={{ color: color.text }}>by how it blinks</b>, not how bright it is, and holds it on bore-sight.
          </div>
          <div style={{ display: "flex", gap: 14, fontFamily: font.mono, fontSize: 22, fontWeight: 600 }}>
            {["Point", "Acquire", "Track"].map((word, i) => (
              <span key={word} style={{ padding: "8px 18px", borderRadius: 999, background: i === 2 ? color.okSoft : color.accentSoft, color: i === 2 ? color.ok : color.accentInk }}>
                {word}
              </span>
            ))}
          </div>
        </div>
        <Tile dark style={{ width: 820, height: 480 }}>
          <Sky lights={BANNER_LIGHTS} frame={BEACON_FRAME} width={820} height={480} />
          <Brackets x={430} y={235} size={58} tone={color.ok} />
          <Label x={470} y={196} tone={color.ok} text="beacon · 5.2 Hz · P 1.00" />
          <Label x={190} y={342} tone="#ffd59a" text="street lamp · steady" />
          <Label x={560} y={80} tone="#ff8a7a" text="tower · 0.5 Hz" />
          <Label x={140} y={70} tone="#fff3d6" text="satellite · steady" />
          <Label x={560} y={362} tone="#ffc27a" text="rival laser · 3 Hz" />
          <div style={{ position: "absolute", left: 22, bottom: 18, fontFamily: font.mono, fontSize: 17, color: "#7f8aa3" }}>NIR 850 nm · 4° × 3°</div>
          <div style={{ position: "absolute", right: 22, bottom: 16, fontFamily: font.mono, fontSize: 17, fontWeight: 700, color: color.ok }}>● LOCKED 1.03 s</div>
        </Tile>
      </div>
    </Page>
  );
}

function Label({ x, y, text, tone }: { x: number; y: number; text: string; tone: string }) {
  return <div style={{ position: "absolute", left: x, top: y, fontFamily: font.mono, fontSize: 16, fontWeight: 600, color: tone, whiteSpace: "nowrap", textShadow: "0 1px 6px #000" }}>{text}</div>;
}

// ---------- Features 1920×900

const FEATURES: { title: string; body: string; glyph: ReactNode }[] = [
  { title: "Finds it by its blink", body: "Every light is Fourier-analysed and scored beacon vs clutter. Brightness is never trusted.", glyph: <Wave /> },
  { title: "Learns the signature", body: "Rate, depth and duty cycle learned while locked, saved to JSON, loaded on real hardware.", glyph: <Big>≋</Big> },
  { title: "Six terminals", body: "Drone, aircraft, ship, LEO, GEO, ISS, and satellite-to-satellite crosslinks.", glyph: <Big>6</Big> },
  { title: "Eight hazards", body: "Fog, rain, shimmer, noise, vibration, glare, occlusion and decoys, freely combined.", glyph: <Big>8</Big> },
  { title: "Same code on video", body: "Load a recording and the identical detector, identifier and tracker run on it.", glyph: <Big>▶</Big> },
  { title: "28 of 28 cases pass", body: "Deterministic, seeded validation. The known failing seeds are published too.", glyph: <Big>✓</Big> },
];

function Big({ children }: { children: ReactNode }) {
  return <span style={{ fontFamily: font.display, fontSize: 40, fontWeight: 600, color: color.accentInk }}>{children}</span>;
}

function Wave() {
  const pts = new Array(9).fill(0).map((_, i) => `${i * 7},${i % 2 ? 6 : 26} ${i * 7 + 7},${i % 2 ? 6 : 26}`);
  return (
    <svg width="60" height="32">
      <polyline points={pts.join(" ")} fill="none" stroke={color.accentInk} strokeWidth="3" strokeLinejoin="round" />
    </svg>
  );
}

export function Features() {
  return (
    <Page>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 34, height: "100%" }}>
        {FEATURES.map((feature) => (
          <Tile key={feature.title} style={{ padding: 44, display: "flex", flexDirection: "column", gap: 20 }}>
            <div style={{ flex: "none", width: 84, height: 84, borderRadius: 20, background: color.accentSoft, display: "flex", alignItems: "center", justifyContent: "center" }}>{feature.glyph}</div>
            <div style={{ fontFamily: font.display, fontWeight: 600, fontSize: 42, letterSpacing: "-0.02em" }}>{feature.title}</div>
            <div style={{ fontSize: 26, lineHeight: 1.45, color: color.text2 }}>{feature.body}</div>
          </Tile>
        ))}
      </div>
    </Page>
  );
}

// ---------- Terminals 1920×720

export function TerminalGlyph({ index, size = 90, tone = color.accentInk }: { index: number; size?: number; tone?: string }) {
  const s = { fill: "none", stroke: tone, strokeWidth: 2.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const paths = [
    // drone
    <g key="d" {...s}><circle cx="10" cy="10" r="6" /><circle cx="38" cy="10" r="6" /><circle cx="10" cy="38" r="6" /><circle cx="38" cy="38" r="6" /><path d="M14 14l20 20M34 14L14 34" /><rect x="19" y="19" width="10" height="10" rx="2" /></g>,
    // aircraft
    <g key="a" {...s}><path d="M24 4v40M6 26l18-8 18 8M16 42l8-4 8 4" /></g>,
    // ship
    <g key="s" {...s}><path d="M6 30h36l-5 10H11z" /><path d="M24 8v22M24 12l10 12H24" /><circle cx="24" cy="7" r="2" fill={tone} /></g>,
    // LEO satellite
    <g key="l" {...s}><rect x="19" y="19" width="10" height="10" rx="1" /><path d="M4 16h13v16H4zM31 16h13v16H31zM17 24h2M29 24h2" /></g>,
    // GEO relay
    <g key="g" {...s}><circle cx="24" cy="24" r="18" strokeDasharray="3 4" /><circle cx="24" cy="24" r="6" /><rect x="36" y="4" width="8" height="8" rx="1" /></g>,
    // station
    <g key="i" {...s}><path d="M4 24h40M12 12v24M36 12v24" /><rect x="7" y="12" width="10" height="24" /><rect x="31" y="12" width="10" height="24" /><rect x="20" y="20" width="8" height="8" /></g>,
  ];
  return (
    <svg width={size} height={size} viewBox="0 0 48 48">
      {paths[index]}
    </svg>
  );
}

export function Terminals() {
  return (
    <Page pad={60}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 26, height: "100%" }}>
        {TERMINALS.map((terminal, i) => (
          <Tile key={terminal.name} style={{ padding: "44px 28px", display: "flex", flexDirection: "column", alignItems: "center", gap: 18, textAlign: "center" }}>
            <div style={{ width: 150, height: 150, borderRadius: 36, background: i >= 3 ? color.night : color.accentSoft, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <TerminalGlyph index={i} tone={i >= 3 ? color.accent : color.accentInk} />
            </div>
            <div style={{ fontFamily: font.display, fontWeight: 600, fontSize: 34, letterSpacing: "-0.02em" }}>{terminal.name}</div>
            <div style={{ fontSize: 22, color: color.text2 }}>{terminal.pattern}</div>
            <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 6, fontFamily: font.mono }}>
              <span style={{ fontSize: 40, fontWeight: 700, color: color.ok }}>{terminal.acq}</span>
              <span style={{ fontSize: 18, color: color.text3 }}>to lock · {terminal.err}</span>
            </div>
          </Tile>
        ))}
      </div>
    </Page>
  );
}

// ---------- Architecture 1920×760

const STAGES = [
  { name: "Frame source", sub: "sim · video · live camera", rate: "" },
  { name: "Detector", sub: "top-hat · matched filter · CFAR", rate: "" },
  { name: "Identifier", sub: "tracklets · FFT · naive Bayes", rate: "" },
  { name: "Kalman tracker", sub: "LOS angles · Singer model", rate: "" },
  { name: "Acquisition FSM", sub: "search → lock → reacquire", rate: "" },
  { name: "Controller", sub: "FF + PI → sim or serial gimbal", rate: "" },
];

export function Architecture() {
  return (
    <Page pad={70}>
      <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 44 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 0, marginTop: 40 }}>
          {STAGES.map((stage, i) => (
            <div key={stage.name} style={{ display: "flex", alignItems: "center", flex: 1 }}>
              <Tile dark={i === 2} style={{ flex: 1, padding: "34px 24px", height: 230, display: "flex", flexDirection: "column", gap: 14 }}>
                <div style={{ fontFamily: font.mono, fontSize: 18, fontWeight: 700, color: i === 2 ? color.accent : color.text3 }}>0{i + 1}</div>
                <div style={{ fontFamily: font.display, fontWeight: 600, fontSize: 32, letterSpacing: "-0.02em", color: i === 2 ? "#fff" : color.text }}>{stage.name}</div>
                <div style={{ fontSize: 21, lineHeight: 1.4, color: i === 2 ? "#aab4c8" : color.text2 }}>{stage.sub}</div>
              </Tile>
              {i < STAGES.length - 1 && (
                <svg width="46" height="24" style={{ flex: "none" }}>
                  <path d="M4 12h34M30 5l8 7-8 7" fill="none" stroke={color.accent} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 26 }}>
          <Band tone={color.accentInk} soft={color.accentSoft} label="Vision thread · 30 Hz" span={5} />
          <Band tone={color.ok} soft={color.okSoft} label="Control thread · 60 Hz" span={1} />
        </div>
        <div style={{ display: "flex", gap: 20, alignItems: "center", fontFamily: font.mono, fontSize: 22, fontWeight: 600 }}>
          <span style={{ color: color.text3 }}>Acquisition FSM</span>
          {["SEARCH", "ACQUIRING", "LOCKED ⇄ COASTING", "REACQUIRE"].map((state, i) => (
            <span key={state} style={{ padding: "8px 18px", borderRadius: 999, background: i === 2 ? color.okSoft : i === 0 ? "rgba(138,144,156,0.15)" : color.warnSoft, color: i === 2 ? color.ok : i === 0 ? color.text2 : color.warn }}>
              {state}
            </span>
          ))}
          <span style={{ marginLeft: "auto", color: color.text3 }}>GUI reads immutable snapshots · never blocks either loop</span>
        </div>
      </div>
    </Page>
  );
}

function Band({ tone, soft, label, span }: { tone: string; soft: string; label: string; span: number }) {
  return (
    <div style={{ flex: span, padding: "16px 24px", borderRadius: 16, background: soft, color: tone, fontFamily: font.mono, fontSize: 22, fontWeight: 700, borderTop: `3px solid ${tone}` }}>
      {label}
    </div>
  );
}
