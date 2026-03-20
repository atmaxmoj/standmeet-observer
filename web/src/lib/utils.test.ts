import { describe, it, expect, vi, afterEach } from "vitest";
import { timeAgo, fmtTime, fmtTokens } from "./utils";

describe("timeAgo", () => {
  afterEach(() => vi.useRealTimers());

  it("returns empty for empty input", () => {
    expect(timeAgo("")).toBe("");
  });

  it("returns empty for invalid date", () => {
    expect(timeAgo("not-a-date")).toBe("");
  });

  it("returns seconds ago", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-20T12:00:30Z"));
    expect(timeAgo("2026-03-20T12:00:00Z")).toBe("30s ago");
  });

  it("returns minutes ago", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-20T12:05:00Z"));
    expect(timeAgo("2026-03-20T12:00:00Z")).toBe("5m ago");
  });

  it("returns hours ago", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-20T15:00:00Z"));
    expect(timeAgo("2026-03-20T12:00:00Z")).toBe("3h ago");
  });

  it("returns days ago", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-23T12:00:00Z"));
    expect(timeAgo("2026-03-20T12:00:00Z")).toBe("3d ago");
  });

  it("returns just now for future dates", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-20T12:00:00Z"));
    expect(timeAgo("2026-03-20T12:01:00Z")).toBe("just now");
  });

  it("handles bare SQLite timestamps (no timezone suffix)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-20T12:00:30Z"));
    expect(timeAgo("2026-03-20 12:00:00")).toBe("30s ago");
  });
});

describe("fmtTime", () => {
  it("returns empty for empty input", () => {
    expect(fmtTime("")).toBe("");
  });

  it("returns empty for invalid date", () => {
    expect(fmtTime("garbage")).toBe("");
  });

  it("returns a formatted string for valid date", () => {
    const result = fmtTime("2026-03-20T12:00:00Z");
    expect(result).toBeTruthy();
    expect(typeof result).toBe("string");
  });
});

describe("fmtTokens", () => {
  it("formats millions", () => {
    expect(fmtTokens(1_500_000)).toBe("1.5M");
  });

  it("formats thousands", () => {
    expect(fmtTokens(2_500)).toBe("2.5k");
  });

  it("formats small numbers as-is", () => {
    expect(fmtTokens(42)).toBe("42");
  });

  it("formats exactly 1M", () => {
    expect(fmtTokens(1_000_000)).toBe("1.0M");
  });

  it("formats exactly 1k", () => {
    expect(fmtTokens(1_000)).toBe("1.0k");
  });

  it("formats zero", () => {
    expect(fmtTokens(0)).toBe("0");
  });
});
