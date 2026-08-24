/**
 * Lint rules for the front end.
 *
 * Deliberately short. `tsc` already rejects unused variables, bad imports and
 * wrong types, and the production build already rejects a Tailwind class that
 * resolves to nothing — so this file carries only what neither of those can
 * see, and every rule in it is here because something actually went wrong.
 */
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/** Tailwind's own palette, which a theme cannot follow. */
const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|" +
  "teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const RAW_COLOR = `\\b(text|bg|border|ring|fill|stroke|from|via|to)-(${PALETTE})-[0-9]{2,3}\\b`;
const RAW_COLOR_MESSAGE =
  "Color comes from semantic tokens — bg-card, text-muted-foreground. A raw " +
  "palette utility cannot follow a palette change.";

export default tseslint.config(
  { ignores: ["dist/**", ".shots/**", "scripts/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser, parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      /**
       * Hooks, from the compiler's own plugin. `static-components` is the one
       * that has already bitten: a component declared inside another is a new
       * function every render, so React sees a new element type and remounts
       * the subtree. A `Shell` inside `App` meant every panel refetched and
       * lost its scroll position whenever anything above it changed, and
       * nothing failed — it was only slow and forgetful.
       */
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "react-hooks/static-components": "error",
      "react-hooks/set-state-in-effect": "error",

      "no-restricted-syntax": [
        "error",
        {
          /**
           * Tooltips go through components/ui/tooltip.tsx. A native one cannot
           * be styled, waits a second before appearing, and never shows on
           * keyboard focus — so a control whose only label is a `title` has no
           * label at all for anyone not using a mouse.
           *
           * Host elements only: `title` is a legitimate prop name on our own
           * components, and <Empty title="..."> is not a tooltip.
           */
          selector: 'JSXOpeningElement[name.name=/^[a-z]/] > JSXAttribute[name.name="title"]',
          message: "Use <Tooltip> — a native title is invisible to keyboard focus and cannot be styled.",
        },
        { selector: `Literal[value=/${RAW_COLOR}/]`, message: RAW_COLOR_MESSAGE },
        { selector: `TemplateElement[value.raw=/${RAW_COLOR}/]`, message: RAW_COLOR_MESSAGE },
      ],
    },
  },
  {
    /**
     * `m` components carry no animation code of their own; the feature set
     * arrives in a second chunk after first paint. Importing `motion` itself,
     * or a feature bundle, pulls the whole library into the entry bundle —
     * which is the thing check-bundle budgets. `motion-features.ts` is the one
     * module whose job is to load it.
     */
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/lib/motion-features.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "motion/react",
              importNames: ["motion", "domAnimation", "domMax"],
              message: "Use `m` with LazyMotion, or the whole library lands in the entry bundle.",
            },
          ],
        },
      ],
    },
  },
);
