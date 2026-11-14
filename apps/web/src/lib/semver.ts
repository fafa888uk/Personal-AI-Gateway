/**
 * Semver-ish comparison for the version check. Mirrors
 * apps/flutter/lib/sse.dart `compareVersions`: numeric parts compare
 * numerically; missing parts count as 0; a pre-release suffix (after `-`)
 * sorts below the same release.
 *
 * Returns -1 if a < b, 0 if equal, 1 if a > b.
 */
export function compareSemver(a: string, b: string): number {
  const core = (v: string) => v.split("-")[0];
  const pre = (v: string) => {
    const idx = v.indexOf("-");
    return idx >= 0 ? v.slice(idx + 1) : "";
  };

  const aParts = core(a).split(".");
  const bParts = core(b).split(".");
  const len = Math.max(aParts.length, bParts.length);
  for (let i = 0; i < len; i++) {
    const av = i < aParts.length ? parseInt(aParts[i], 10) || 0 : 0;
    const bv = i < bParts.length ? parseInt(bParts[i], 10) || 0 : 0;
    if (av !== bv) return av < bv ? -1 : 1;
  }
  const ap = pre(a);
  const bp = pre(b);
  if (ap === bp) return 0;
  if (ap === "") return 1; // release > pre-release
  if (bp === "") return -1;
  return ap < bp ? -1 : 1;
}

/** True when `latest` is strictly newer than `current`. */
export function isNewerVersion(current: string, latest: string): boolean {
  return compareSemver(current, latest) < 0;
}
