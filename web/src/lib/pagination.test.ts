import { describe, it, expect } from "vitest";
import { buildPageNumbers } from "@/lib/pagination";

describe("buildPageNumbers", () => {
  it("returns all pages when total <= 7", () => {
    expect(buildPageNumbers(1, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(buildPageNumbers(3, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("returns single page", () => {
    expect(buildPageNumbers(1, 1)).toEqual([1]);
  });

  it("shows ellipsis for large total, current at start", () => {
    const result = buildPageNumbers(1, 20);
    expect(result[0]).toBe(1);
    expect(result[1]).toBe(2);
    expect(result).toContain("...");
    expect(result[result.length - 1]).toBe(20);
  });

  it("shows ellipsis for large total, current at end", () => {
    const result = buildPageNumbers(20, 20);
    expect(result[0]).toBe(1);
    expect(result).toContain("...");
    expect(result[result.length - 2]).toBe(19);
    expect(result[result.length - 1]).toBe(20);
  });

  it("shows both ellipses for current in middle", () => {
    const result = buildPageNumbers(10, 20);
    expect(result[0]).toBe(1);
    expect(result[result.length - 1]).toBe(20);
    // Should have two "..." sections
    const dots = result.filter((p) => p === "...");
    expect(dots.length).toBe(2);
    // Current and neighbors should be present
    expect(result).toContain(9);
    expect(result).toContain(10);
    expect(result).toContain(11);
  });

  it("merges ellipsis when current is near start", () => {
    const result = buildPageNumbers(3, 20);
    expect(result).toContain(1);
    expect(result).toContain(2);
    expect(result).toContain(3);
    expect(result).toContain(4);
    expect(result).toContain(20);
  });

  it("merges ellipsis when current is near end", () => {
    const result = buildPageNumbers(18, 20);
    expect(result).toContain(1);
    expect(result).toContain(17);
    expect(result).toContain(18);
    expect(result).toContain(19);
    expect(result).toContain(20);
  });
});
