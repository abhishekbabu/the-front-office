# 1. Never test the framework

Test what this app decided, not what a dependency already guarantees. Pydantic
validates, FastAPI routes, `json` round-trips and `dict` keeps its keys — none
of that is this repo's behavior, and a test asserting it fails only when a
dependency upgrade changes something the upgrade notes already told you.

## Reject

```python
def test_scout_report_has_a_headline() -> None:
    report = ScoutReport(headline="x", ...)
    assert report.headline == "x"          # pydantic assigning a field


def test_the_api_returns_json() -> None:
    assert client.get("/api/competitions").headers["content-type"] == "application/json"
```

## Keep

```python
def test_the_engine_overwrites_whatever_headline_the_model_returned() -> None:
    """A hallucinated rank sits in the header looking exactly as authoritative
    as a real one, so the engine fills it from the provider's context."""
```

The first pair tests pydantic and Starlette. The second tests a rule this repo
argued itself into, recorded in `AGENTS.md`, and would silently lose in a
refactor.

## The test

Ask: *if I deleted this app's code and kept the dependencies, would this test
still pass?* If yes, it is testing the framework. Delete it.
