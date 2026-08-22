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


MOCK_SCOUT_REPORT = """### **Scout Report**

**Matchup Insight**: [MOCK] We are positioned for a 6-3 victory. Focus on securing REB and protecting our FG% lead.

**Top Targets**:
- **ADD Mock Player 1 (PF)**: [MOCK] Provides elite rebounding and efficient shooting. -> **DROP Bench Warmer**: Minimal production.
- **ADD Mock Player 2 (C)**: [MOCK] Strong blocks and rebounds contributor. -> **DROP Injured Reserve**: Currently out.
- **ADD Mock Player 3 (SG)**: [MOCK] High-volume 3PT shooter to secure our lead. -> **DROP Inconsistent Guard**: Poor recent performance.

**Final Strategy**: [MOCK] Add efficient, multi-category contributors to secure the win."""

MOCK_TRADE_REPORT = """- **Verdict**: [MOCK] Accept. The incoming side is the better rest-of-season value.
- **Impact**: [MOCK] Net gain in REB and BLK, roughly neutral in AST, slight FT% dip.
- **Shutdown Risk**: [MOCK] Neither incoming player is on a tanking team.
- **Strategy**: [MOCK] Accept, then stream a guard to cover the AST dip."""


class MockChatSession:
    """Simulates a genai.chats.Chat object for testing.

    The first message a caller sends is the generated analysis prompt, so it is
    answered with a report of the right *shape* — otherwise `--mock` exercises
    none of the report-rendering path it exists to test. Subsequent messages are
    interactive follow-ups and get short canned replies.
    """

    def __init__(self) -> None:
        self._turns = 0

    def send_message(self, message: str | list[str] | Any) -> MockResponse:
        content = str(message)
        self._turns += 1
        if self._turns == 1:
            return MockResponse(self._initial_report(content))
        return MockResponse(self._followup(content))

    @staticmethod
    def _initial_report(prompt: str) -> str:
        if "Trade Evaluation Request" in prompt or "Giving Away" in prompt:
            return MOCK_TRADE_REPORT
        return MOCK_SCOUT_REPORT

    @staticmethod
    def _followup(content: str) -> str:
        content_lower = content.lower()
        if "why" in content_lower:
            return "[MOCK] I recommended this player because they fit your punt strategy perfectly."
        elif "explain" in content_lower:
            return "[MOCK] The strategy focuses on maximizing FG% and Rebounds."
        else:
            return "[MOCK] That's a great question. Based on the stats, we should proceed with the add."


class HistoryItem(TypedDict):
    role: str
    parts: list[str]
