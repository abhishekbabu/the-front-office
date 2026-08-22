"""
Type definitions for Gemini Client.
"""

from typing import Any, Protocol, TypedDict


class ResponseProtocol(Protocol):
    text: str | None


class ChatSession(Protocol):
    def send_message(self, message: str | list[str] | Any) -> ResponseProtocol: ...


class MockResponse:
    def __init__(self, text: str | None):
        self.text = text


class MockChatSession:
    """Simulates a genai.chats.Chat object for testing.

    Only ever carries follow-up questions: reports themselves come back as typed
    models from GeminiClient.generate_structured, which has its own canned value.
    """

    def send_message(self, message: str | list[str] | Any) -> MockResponse:
        content = str(message).lower()
        if "why" in content:
            return MockResponse("[MOCK] That player fits the punt strategy and the close categories.")
        if "explain" in content:
            return MockResponse("[MOCK] The plan maximises FG% and REB while conceding PTS.")
        return MockResponse("[MOCK] Based on the numbers, proceed with the recommended move.")


class HistoryItem(TypedDict):
    role: str
    parts: list[str]
