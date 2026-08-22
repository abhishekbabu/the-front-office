"""
Gemini AI Client wrapper.
"""

import logging
from typing import TYPE_CHECKING

from google import genai
from google.genai.chats import Chat

from the_front_office.config.settings import settings
from the_front_office.exceptions import AIResponseError, AIUnavailableError

from .constants import MODEL_FLASH, MODEL_PRO
from .types import HistoryItem, MockChatSession

if TYPE_CHECKING:
    from the_front_office.trade.types import TradeProposal

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self, api_key: str | None = settings.gemini_api_key, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.chat: Chat | MockChatSession | None = None

        if self.mock_mode:
            logger.debug("🎭 Mock AI mode enabled - using canned responses")
            self.client = None
        elif not api_key:
            logger.warning("GOOGLE_API_KEY not found. AI features will be disabled.")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)

    def start_chat(
        self, initial_history: list[HistoryItem] | None = None, enable_search: bool = False
    ) -> Chat | MockChatSession:
        """Start a chat session with the model."""
        if self.mock_mode:
            return MockChatSession()

        if not self.client:
            raise AIUnavailableError()

        config = None
        if enable_search:
            from google.genai import types

            search_tool = types.Tool(google_search=types.GoogleSearch())
            config = types.GenerateContentConfig(tools=[search_tool])

        # Cast or transform history if needed, but genai accepts flexible types.
        # Strict typing here ensures we pass structure.
        # For simplicity with genai API which is complex typed, we can assume it accepts our dicts.
        return self.client.chats.create(
            model=MODEL_PRO,
            history=initial_history,  # type: ignore[arg-type]
            config=config,
        )

    def parse_trade_string(self, text: str) -> "TradeProposal":
        """
        Parse a natural language trade string into a structured TradeProposal.
        Uses Gemini Flash for speed and cost efficiency.
        """
        from the_front_office.trade.types import TradeProposal

        if self.mock_mode:
            # Return a hardcoded mock trade for testing
            return TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])

        if not self.client:
            raise AIUnavailableError()

        # Use Gemini Flash for parsing tasks
        prompt = f"""
        Extract the players being given and received in this trade offer.
        Return ONLY a JSON object with keys "giving" and "receiving".
        Using full player names.

        Trade: "{text}"
        """

        try:
            response = self.client.models.generate_content(
                model=MODEL_FLASH, contents=prompt, config={"response_mime_type": "application/json"}
            )

            import json

            text = response.text or "{}"
            data = json.loads(text)
            # Ensure we always return lists even if AI returns strings
            giving = data.get("giving", [])
            receiving = data.get("receiving", [])

            if isinstance(giving, str):
                giving = [giving]
            if isinstance(receiving, str):
                receiving = [receiving]

            return TradeProposal(giving=giving, receiving=receiving)
        except Exception as e:
            logger.error(f"Error parsing trade string: {e}")
            raise AIResponseError(f"Trade parsing failed: {e}") from e
