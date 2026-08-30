import { describe, expect, it } from "vitest";

import { scalarText } from "./format";

describe("scalarText", () => {
  it.each([
    ["text", "text"],
    [42, "42"],
    [true, "true"],
    [{ unsafe: "object" }, "—"],
    [null, "—"],
  ])("formats %j as a safe scalar", (input, expected) => {
    expect(scalarText(input)).toBe(expected);
  });
});
