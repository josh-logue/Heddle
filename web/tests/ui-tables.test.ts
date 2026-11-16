// Tables the interface shows, kept in step with the data they describe.
import { describe, expect, it } from "vitest";
import { DISPLAY_TOGGLES } from "../src/core/model.ts";
import { SECTIONS } from "../src/ui/Tools.tsx";

describe("Board Options", () => {
  it("offers every on/off display option exactly once", () => {
    const offered = SECTIONS.flatMap(([, options]) => options.map(([key]) => key));
    expect([...offered].sort()).toEqual([...DISPLAY_TOGGLES].sort());
  });
});
