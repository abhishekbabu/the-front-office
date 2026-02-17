"""
Type definitions for Gemini Client.
"""
from typing import Optional, Union, Protocol, TypedDict, List, Any

class ResponseProtocol(Protocol):
    text: Optional[str]

class ChatSession(Protocol):
    def send_message(self, message: Union[str, List[str], Any]) -> ResponseProtocol: ...

class MockResponse:
    def __init__(self, text: Optional[str]):
        self.text = text

class MockChatSession:
    """Simulates a genai.chats.Chat object for testing."""
    def send_message(self, message: Union[str, List[str], Any]) -> MockResponse:
        content = str(message)
        return MockResponse(self._get_response(content))

    def _get_response(self, content: str) -> str:
        content_lower = content.lower()
        if "why" in content_lower:
            return "[MOCK] I recommended this player because they fit your punt strategy perfectly."
        elif "explain" in content_lower:
            return "[MOCK] The strategy focuses on maximizing FG% and Rebounds."
        else:
            return "[MOCK] That's a great question. Based on the stats, we should proceed with the add."

class HistoryItem(TypedDict):
    role: str
    parts: List[str]
