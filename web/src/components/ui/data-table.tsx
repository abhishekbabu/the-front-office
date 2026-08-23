import { ArrowDown, ArrowUp } from "lucide-react";
import { m } from "motion/react";
import { list, listItem } from "@/lib/motion";
import { Table, Td, Th } from "@/components/ui/table";
import { cn } from "@/lib/utils";

/**
 * A table whose columns come from the data.
 *
 * Every sport names its own — FPL sends Price and xGI, football sends Depth —
 * so a client that hard-codes columns has to learn each sport. This reads the
 * keys off the first row and renders whatever arrives, which is also what
 * makes adding a sport a backend change alone.
 */
export type SortState = { column: string; descending: boolean };

export function DataTable<Row extends { player_id: string; columns: Record<string, string> }>({
  rows,
  numeric,
  render,
  onSelect,
  sort,
  onSort,
}: {
  rows: Row[];
  /** Columns whose values are figures, so they align right like numbers. */
  numeric?: Set<string>;
  /** Per-column rendering, for the few that are more than text. */
  render?: (column: string, value: string, row: Row) => React.ReactNode;
  onSelect?: (row: Row) => void;
  /** The column currently ordering the rows, where anything is. */
  sort?: SortState | null;
  /**
   * Called when a header is clicked. Its presence is what makes the table
   * sortable: a caller holding the whole list passes one that sorts locally,
   * and a caller holding one page of four thousand passes one that asks the
   * server — which is the only correct answer there, since sorting fifty rows
   * of a ranking answers a different question than sorting the ranking.
   */
  onSort?: (next: SortState) => void;
}) {
  const columns = rows[0] ? Object.keys(rows[0].columns) : [];
  const isNumeric = (column: string) => numeric?.has(column) ?? false;
  const isActive = (column: string) => sort?.column === column;

  return (
    <Table>
      <thead>
        <tr>
          {columns.map((column) => (
            <Th key={column} className={cn(isNumeric(column) && "text-right", onSort && "p-0")}>
              {onSort ? (
                <button
                  type="button"
                  onClick={() => onSort({ column, descending: !isActive(column) || !sort?.descending })}
                  aria-label={`Sort by ${column}`}
                  className={cn(
                    "flex w-full items-center gap-1 px-3 py-2 transition-colors hover:text-foreground",
                    isNumeric(column) && "justify-end",
                    isActive(column) && "text-foreground",
                  )}
                >
                  {column}
                  {/* Only the active column carries an arrow. One on every
                      header is decoration; one on the sorted column is the
                      answer to "what am I looking at". */}
                  {isActive(column) &&
                    (sort?.descending ? (
                      <ArrowDown className="size-3 shrink-0" aria-hidden />
                    ) : (
                      <ArrowUp className="size-3 shrink-0" aria-hidden />
                    ))}
                </button>
              ) : (
                column
              )}
            </Th>
          ))}
        </tr>
      </thead>
      <m.tbody variants={list} initial="hidden" animate="shown">
        {rows.map((row) => (
          // A motion row rather than a wrapped one: anything between <tbody>
          // and <tr> breaks the table's own layout.
          <m.tr
            key={row.player_id}
            variants={listItem}
            onClick={onSelect && (() => onSelect(row))}
            onKeyDown={onSelect && ((e: React.KeyboardEvent) => e.key === "Enter" && onSelect(row))}
            tabIndex={onSelect ? 0 : undefined}
            className={cn("hover:bg-muted", onSelect && "cursor-pointer")}
          >
            {columns.map((column) => {
              const value = row.columns[column] ?? "";
              return (
                <Td key={column} className={cn(isNumeric(column) && "text-right")}>
                  {render?.(column, value, row) ?? value}
                </Td>
              );
            })}
          </m.tr>
        ))}
      </m.tbody>
    </Table>
  );
}
