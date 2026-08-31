# 3. Test invariants, not snapshots

A hardcoded copy of today's output tests that nothing changed, not that the
rule holds. It goes stale the first time a legitimate value is added, and the
fix is always to paste the new output in — which teaches everyone that a red
test means "update the expected value", the exact reflex you do not want.

## Reject

```python
def test_scout_categories() -> None:
    assert SCOUT_CATEGORIES == {"PTS": "points", "REB": "rebounds", "AST": "assists"}
```

Adding a category breaks it for no reason, and the fix teaches nothing.

## Keep

```python
def test_every_scoutable_category_has_a_display_name() -> None:
    assert all(name and name.islower() for name in SCOUT_CATEGORIES.values())


def test_every_month_has_a_name() -> None:
    assert all(_month_name(m) for m in range(1, 13))
```

These state the property that must hold for *any* member — which is the actual
rule, and which keeps holding as the set grows.

## When a literal is right

Pin the exact value when the value itself is the contract with an outside
system: a wire format, a cache key layout, a rendered date. `"2026-09-01"` in a
date-formatting test is the specification, not a snapshot.
