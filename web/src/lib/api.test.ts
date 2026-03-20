import { describe, it, expect } from "vitest";
import { qs } from "./api";

describe("qs", () => {
  it("builds query string from params", () => {
    expect(qs({ limit: 20, offset: 0, search: "hello" })).toBe(
      "limit=20&offset=0&search=hello"
    );
  });

  it("filters out empty string values", () => {
    expect(qs({ limit: 20, search: "" })).toBe("limit=20");
  });

  it("keeps numeric zero", () => {
    expect(qs({ offset: 0 })).toBe("offset=0");
  });

  it("encodes special characters", () => {
    expect(qs({ search: "hello world" })).toBe("search=hello%20world");
  });

  it("returns empty string for no valid params", () => {
    expect(qs({ search: "" })).toBe("");
  });
});
