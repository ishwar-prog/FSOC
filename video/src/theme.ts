import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

// Taken from ui/theme.py so the videos match the app.
export const color = {
  bg: "#f1f2f6",
  surface: "#ffffff",
  surface2: "#f7f8fa",
  line: "rgba(11, 17, 32, 0.08)",
  lineStrong: "rgba(11, 17, 32, 0.14)",
  text: "#0b1120",
  text2: "#5a6070",
  text3: "#8a909c",
  accent: "#44b6ff",
  accentInk: "#0a5c96",
  accentSoft: "rgba(68, 182, 255, 0.12)",
  ok: "#08b44d",
  okSoft: "rgba(8, 180, 77, 0.12)",
  warn: "#b8801b",
  warnSoft: "rgba(184, 128, 27, 0.12)",
  bad: "#c93b37",
  badSoft: "rgba(201, 59, 55, 0.12)",
  night: "#0b1120",
  night2: "#141c30",
};

// Acquisition FSM, as named in fsoc/core/pipeline.py.
export const STATE_COLOR: Record<string, string> = {
  SEARCH: "#8a909c",
  ACQUIRING: color.warn,
  LOCKED: color.ok,
  COASTING: color.accent,
  REACQUIRE: color.warn,
};

export const font = {
  display: "Space Grotesk",
  text: "Inter",
  mono: "JetBrains Mono",
};

export const shadow = "0 30px 70px -34px rgba(11, 17, 32, 0.30), 0 2px 6px rgba(11, 17, 32, 0.05)";

export function loadFonts(): Promise<unknown> {
  return Promise.all([
    loadFont({ family: font.display, url: staticFile("fonts/space-grotesk-latin-wght-normal.woff2"), weight: "300 700" }),
    loadFont({ family: font.text, url: staticFile("fonts/inter-latin-wght-normal.woff2"), weight: "100 900" }),
    loadFont({ family: font.mono, url: staticFile("fonts/jetbrains-mono-latin-wght-normal.woff2"), weight: "100 800" }),
  ]);
}

// Headline numbers: python benchmark.py, 40 s runs, seed 42 (README section 3).
export const TERMINALS = [
  { name: "Drone", pattern: "Hover Hold", acq: "1.03 s", err: "0.02 px" },
  { name: "Aircraft", pattern: "Figure-Eight", acq: "1.20 s", err: "0.03 px" },
  { name: "Ship", pattern: "Transit", acq: "0.83 s", err: "0.03 px" },
  { name: "LEO satellite", pattern: "Pass", acq: "1.20 s", err: "0.02 px" },
  { name: "GEO relay", pattern: "36 000 km", acq: "1.20 s", err: "0.03 px" },
  { name: "Space station", pattern: "ISS Pass", acq: "1.20 s", err: "0.02 px" },
];

export const TARGETS = [
  { label: "Acquisition", target: "≤ 2 s", value: "1.03 s" },
  { label: "Tracking error", target: "≤ 10 px", value: "0.02 px" },
  { label: "Target loss", target: "< 5 %", value: "2.91 %" },
  { label: "Re-acquisition", target: "≤ 1 s", value: "0.17 s" },
  { label: "Processing", target: "≥ 20 FPS", value: "30 FPS" },
  { label: "Control loop", target: "≥ 20 Hz", value: "60 Hz" },
];

export const HAZARDS = ["Fog", "Rain", "Heat shimmer", "Sensor noise", "Mount vibration", "Sun glare", "Occlusion", "Decoy lights"];

export const BENCH = [
  ["Drone · Hover Hold", "1.03 s", "0.02 px", "2.91 %", "0.17 s"],
  ["Aircraft · Linear Flyby", "1.23 s", "0.03 px", "2.92 %", "0.17 s"],
  ["Aircraft · Figure-Eight", "1.20 s", "0.03 px", "2.92 %", "0.17 s"],
  ["Ship · Transit", "0.83 s", "0.03 px", "2.89 %", "0.17 s"],
  ["Satellite · LEO Pass", "1.20 s", "0.02 px", "3.35 %", "0.33 s"],
  ["Satellite · GEO Relay", "1.20 s", "0.03 px", "4.98 %", "0.97 s"],
  ["Space station · ISS Pass", "1.20 s", "0.02 px", "3.35 %", "0.33 s"],
  ["Fog 80 %", "1.23 s", "0.09 px", "3.01 %", "0.20 s"],
  ["Heat Shimmer 80 %", "1.20 s", "3.28 px", "2.92 %", "0.17 s"],
  ["Decoy Lights 80 %", "1.23 s", "0.04 px", "2.92 %", "0.17 s"],
  ["Dim beacon · bright blinking decoys", "1.03 s", "0.04 px", "2.91 %", "0.17 s"],
  ["Storm · all hazards stacked", "1.60 s", "2.19 px", "3.04 %", "0.20 s"],
];
