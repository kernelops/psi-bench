import type { Stats } from "./api";

export const fmtNum = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "-" : v.toLocaleString(undefined, { maximumFractionDigits: digits });

export const fmtSeconds = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v < 1 ? `${(v * 1000).toFixed(0)} ms` : `${v.toFixed(v < 10 ? 3 : 2)} s`;

export const fmtMB = (bytes: number | null | undefined, digits = 2) =>
  bytes === null || bytes === undefined ? "-" : `${(bytes / 1e6).toFixed(digits)} MB`;

export const fmtKbAsMB = (kb: number | null | undefined) =>
  kb === null || kb === undefined ? "-" : `${(kb / 1024).toFixed(kb < 10240 ? 1 : 0)} MB`;

export const fmtStats = (s: Stats | undefined, scale = 1, digits = 3) => {
  if (!s || !s.n || s.median === undefined) return "-";
  const base = (s.median * scale).toFixed(digits);
  return s.ci95 !== undefined ? `${base} ±${(s.ci95 * scale).toFixed(digits)}` : base;
};

/** "2^20", "1_048_576", "1048576", "1e6" -> number (NaN if invalid). */
export function parseSize(text: string): number {
  const t = text.trim().replace(/_/g, "").replace(/,/g, "");
  const pow = /^(\d+)\s*\^\s*(\d+)$/.exec(t);
  if (pow) return Math.pow(Number(pow[1]), Number(pow[2]));
  return Number(t);
}

export const parseSizes = (text: string): number[] => text.split(/[\s,;]+/).filter(Boolean).map(parseSize);

export const fmtSizes = (sizes: number[]) => {
  if (sizes.length >= 3 && new Set(sizes).size === 1) return `${sizes.length} parties × ${sizes[0].toLocaleString()}`;
  return sizes.map((s) => s.toLocaleString()).join(" vs ");
};

export const fmtTime = (epoch: number | null | undefined) => (epoch ? new Date(epoch * 1000).toLocaleTimeString() : "-");

export const FAMILY_COLORS: Record<string, string> = {
  PEPSI: "#d1495b",
  "VOLE-PSI": "#2e86ab",
  "BZS-MPSI": "#3a9e5f",
};

export const protocolFamily = (protocol: string) =>
  protocol.startsWith("pepsi") ? "PEPSI" : protocol.startsWith("bzs") ? "BZS-MPSI" : "VOLE-PSI";

export const colorOf = (protocol: string, label?: string) => {
  const base = FAMILY_COLORS[protocolFamily(protocol)];
  if (label && /star/.test(label)) return "#7a5195";
  if (label && /paper-literal/.test(label)) return "#f2a65a";
  return base;
};
