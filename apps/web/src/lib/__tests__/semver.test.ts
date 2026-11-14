import { describe, expect, it } from "vitest";

import { compareSemver, isNewerVersion } from "../semver";

describe("compareSemver", () => {
  it("compares numerically, not lexicographically", () => {
    expect(compareSemver("1.9.0", "1.10.0")).toBe(-1);
    expect(compareSemver("1.10.0", "1.9.0")).toBe(1);
  });

  it("treats missing parts as 0", () => {
    expect(compareSemver("1.0", "1.0.0")).toBe(0);
    expect(compareSemver("1.0.1", "1.0")).toBe(1);
  });

  it("returns 0 for equal versions", () => {
    expect(compareSemver("0.3.0", "0.3.0")).toBe(0);
  });

  it("sorts a pre-release below the same release", () => {
    expect(compareSemver("1.0.0-beta", "1.0.0")).toBe(-1);
    expect(compareSemver("1.0.0", "1.0.0-beta")).toBe(1);
  });

  it("compares pre-release labels lexicographically", () => {
    expect(compareSemver("1.0.0-alpha", "1.0.0-beta")).toBe(-1);
  });
});

describe("isNewerVersion", () => {
  it("is true only when latest is strictly newer", () => {
    expect(isNewerVersion("1.0.0", "1.0.1")).toBe(true);
    expect(isNewerVersion("1.0.1", "1.0.0")).toBe(false);
    expect(isNewerVersion("1.0.0", "1.0.0")).toBe(false);
  });
});
