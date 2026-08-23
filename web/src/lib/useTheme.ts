import { useCallback, useEffect, useState } from "react";
import {
  DEFAULT_PALETTE,
  PALETTE_STORAGE_KEY,
  applyPalette,
  isPaletteId,
  suppressThemeTransitions,
  type PaletteId,
} from "@/themes/registry";

export type Mode = "light" | "dark";

const MODE_STORAGE_KEY = "tfo:mode";

/** What the pre-paint script in index.html already put on <html>. */
function currentMode(): Mode {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function currentPalette(): PaletteId {
  const stored = safeRead(PALETTE_STORAGE_KEY);
  return isPaletteId(stored) ? stored : DEFAULT_PALETTE;
}

/**
 * Storage throws rather than returning null in some contexts — a private
 * window, or a browser set to block site data. A theme preference is a
 * convenience, so failing to read or write one must never take the page down.
 */
function safeRead(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeWrite(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* preference simply will not persist */
  }
}

export function useTheme() {
  const [mode, setModeState] = useState<Mode>(currentMode);
  const [palette, setPaletteState] = useState<PaletteId>(currentPalette);

  const setMode = useCallback((next: Mode) => {
    suppressThemeTransitions();
    document.documentElement.classList.toggle("dark", next === "dark");
    safeWrite(MODE_STORAGE_KEY, next);
    setModeState(next);
  }, []);

  const setPalette = useCallback((next: PaletteId) => {
    suppressThemeTransitions();
    applyPalette(next);
    safeWrite(PALETTE_STORAGE_KEY, next);
    setPaletteState(next);
  }, []);

  // Follow the OS only while the user has expressed no preference of their own.
  useEffect(() => {
    if (safeRead(MODE_STORAGE_KEY)) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => {
      document.documentElement.classList.toggle("dark", e.matches);
      setModeState(e.matches ? "dark" : "light");
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return { mode, setMode, palette, setPalette };
}
