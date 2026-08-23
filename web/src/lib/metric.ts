/**
 * Split a move's metric into the figure and its unit.
 *
 * The model writes this as one free-text string in whatever currency the league
 * scores in — "7.4 xPts", "+3.2 xPts, +1.4 over Smith", "£8.5m, 6.2 xPts",
 * "4 games left" — and it is the number the decision turns on. Promoting the
 * leading figure to display size and demoting the rest to a caption is what
 * makes a column of them scannable.
 *
 * Anything that does not open with a number has no figure to promote, so it is
 * returned whole rather than mangled into a misleading one.
 */
export type Metric = { figure: string; unit: string } | { figure: null; text: string };

const LEADING_FIGURE = /^([+-]?\d[\d.,]*%?)\s*(.*)$/s;

export function splitMetric(metric: string): Metric {
  const trimmed = metric.trim();
  const match = LEADING_FIGURE.exec(trimmed);
  if (!match) return { figure: null, text: trimmed };
  const [, figure, unit] = match;
  return { figure: figure!, unit: (unit ?? "").trim() };
}
