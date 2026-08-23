import { describe, expect, it } from "vitest";
import { splitMetric } from "@/lib/metric";

describe("splitMetric", () => {
  it("promotes a plain figure and keeps its unit", () => {
    expect(splitMetric("7.4 xPts")).toEqual({ figure: "7.4", unit: "xPts" });
  });

  it("keeps a leading sign, which carries the direction of the move", () => {
    expect(splitMetric("+3.2 xPts")).toEqual({ figure: "+3.2", unit: "xPts" });
    expect(splitMetric("-1.5 proj pts")).toEqual({ figure: "-1.5", unit: "proj pts" });
  });

  it("keeps the whole comparison as the caption", () => {
    expect(splitMetric("14.2 proj pts, +4.1 over Smith")).toEqual({
      figure: "14.2",
      unit: "proj pts, +4.1 over Smith",
    });
  });

  it("handles a figure with no unit", () => {
    expect(splitMetric("2")).toEqual({ figure: "2", unit: "" });
  });

  it("handles thousands separators and percentages", () => {
    expect(splitMetric("340,112 overall")).toEqual({ figure: "340,112", unit: "overall" });
    expect(splitMetric("75% chance")).toEqual({ figure: "75%", unit: "chance" });
  });

  it("returns a currency-led metric whole rather than promoting the wrong number", () => {
    // "£8.5m" opens with a symbol, so there is no leading figure to lift out —
    // splitting on the 8 would headline a number that means something else.
    expect(splitMetric("£8.5m, 6.2 xPts")).toEqual({ figure: null, text: "£8.5m, 6.2 xPts" });
  });

  it("returns prose whole", () => {
    expect(splitMetric("no metric")).toEqual({ figure: null, text: "no metric" });
  });

  it("survives an empty metric", () => {
    expect(splitMetric("")).toEqual({ figure: null, text: "" });
  });
});
