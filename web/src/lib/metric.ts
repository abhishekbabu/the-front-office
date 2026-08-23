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

/**
 * A signed number anywhere in the string. A move is ranked by what it changes,
 * so when the metric opens with something else — a price, most often — the
 * delta buried after it is still the figure the row is about.
 */
const SIGNED_FIGURE = /([+-]\d[\d.,]*%?)/;

export function splitMetric(metric: string): Metric {
  const trimmed = metric.trim();

  const leading = LEADING_FIGURE.exec(trimmed);
  if (leading) {
    const [, figure, unit] = leading;
    return { figure: figure!, unit: (unit ?? "").trim() };
  }

  // "£8.5m, +1.4 xPts" opens with a currency symbol, so there is no leading
  // figure — but +1.4 is what the move is worth, and leaving the whole string
  // as small print puts a hole in the column of figures.
  const signed = SIGNED_FIGURE.exec(trimmed);
  if (signed) {
    const figure = signed[1]!;
    const unit = (trimmed.slice(0, signed.index) + trimmed.slice(signed.index + figure.length))
      // Cutting the figure out leaves a gap and can strand a separator.
      .replace(/\s+/g, " ")
      .replace(/\s*,\s*,\s*/g, ", ")
      .replace(/^[\s,]+|[\s,]+$/g, "")
      .trim();
    return { figure, unit };
  }

  return { figure: null, text: trimmed };
}
