"""Stand-ins used when `--mock` skips the real Gemini calls."""


class MockResponse:
    """A response object with only the attribute callers read."""

    def __init__(self, text: str | None):
        self.text = text


class MockChatSession:
    """Stands in for a genai chat.

    Carries follow-up questions only: reports come back as typed models from
    `generate_structured`, which has its own canned value.
    """

    def send_message(self, message: object) -> MockResponse:
        content = str(message).lower()
        if "why" in content:
            return MockResponse("[MOCK] That player fits the punt strategy and the close categories.")
        if "explain" in content:
            return MockResponse("[MOCK] The plan maximises FG% and REB while conceding PTS.")
        return MockResponse("[MOCK] Based on the numbers, proceed with the recommended move.")
