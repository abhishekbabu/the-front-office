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
export function DataTable<Row extends { player_id: string; columns: Record<string, string> }>({
  rows,
  numeric,
  render,
  onSelect,
}: {
  rows: Row[];
  /** Columns whose values are figures, so they align right like numbers. */
  numeric?: Set<string>;
  /** Per-column rendering, for the few that are more than text. */
  render?: (column: string, value: string, row: Row) => React.ReactNode;
  onSelect?: (row: Row) => void;
}) {
  const columns = rows[0] ? Object.keys(rows[0].columns) : [];
  const isNumeric = (column: string) => numeric?.has(column) ?? false;

  return (
    <Table>
      <thead>
        <tr>
          {columns.map((column) => (
            <Th key={column} className={cn(isNumeric(column) && "text-right")}>
              {column}
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
