/**
 * The animation feature set, in its own module so it can be split out.
 *
 * `LazyMotion` only defers what a dynamic import can reach, and an import of
 * `motion/react` from inside the app's entry module resolves to that same
 * bundle — so the split never happens and the whole library lands in the entry
 * chunk. Pointing the import at this file gives the bundler something separable.
 */
export { domAnimation as default } from "motion/react";
