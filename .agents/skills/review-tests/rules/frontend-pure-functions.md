# 10. Pull the logic out and test it directly

Front-end tests here are Vitest units over pure functions, not rendered
components. `web/src/lib/metric.test.ts`, `web/src/lib/route.test.ts` and
`web/src/themes/registry.test.ts` are the pattern: logic lives in a module that
takes values and returns values, and the test calls it.

Rendering a component to reach a calculation buried in it is slow, couples the
assertion to markup, and fails when a class name changes.

## Reject

```tsx
it("formats the projection", () => {
  render(<PlayerRow player={{ projection: 20.34 }} />)
  expect(screen.getByText("20.3")).toBeInTheDocument()   // testing the formatter through the DOM
})
```

## Keep

```ts
it("rounds a projection to one decimal", () => {
  expect(formatProjection(20.34)).toBe("20.3")
})
```

...with `formatProjection` exported from `lib/`.

## What to flag

- A `.test.tsx` that renders only to reach a calculation — extract it to `lib/`
- Logic inside a component or hook with no exported, testable seam
- Assertions on class names or Tailwind utilities: styling is not behavior, and
  `AGENTS.md` already forbids raw palette utilities, so the token is the
  contract and it is checked by review, not by a unit test
- A test for a `components/ui/` primitive that duplicates what the panel test
  already covers

## Where rendering is right

Behavior that only exists in the rendering — an `IconButton`'s `label` being
both tooltip and accessible name, a table holding column widths across a sort.
Those are real behaviors with no pure-function form, and they earn a render.
