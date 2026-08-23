import { describe, expect, it } from "vitest";
import { DEFAULT_PALETTE, PALETTES, applyPalette, isPaletteId } from "@/themes/registry";

describe("palette registry", () => {
  it("registers the default", () => {
    expect(PALETTES.map((p) => p.id)).toContain(DEFAULT_PALETTE);
  });

  it("gives every palette a distinct id", () => {
    expect(new Set(PALETTES.map((p) => p.id)).size).toBe(PALETTES.length);
  });

  it("gives every palette a label, a hint and a swatch for the picker", () => {
    for (const palette of PALETTES) {
      expect(palette.label).toBeTruthy();
      expect(palette.hint).toBeTruthy();
      expect(palette.swatch).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it("rejects an unknown id, so a stale stored value falls back", () => {
    expect(isPaletteId("catppuccin")).toBe(false);
    expect(isPaletteId(null)).toBe(false);
    expect(isPaletteId("floodlight")).toBe(true);
  });

  it("clears the attribute for the default rather than stamping it", () => {
    // The default lives in @theme, so an attribute for it would select a block
    // that does not exist and quietly do nothing.
    applyPalette("floodlight");
    expect(document.documentElement.getAttribute("data-theme")).toBe("floodlight");
    applyPalette(DEFAULT_PALETTE);
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });
});
