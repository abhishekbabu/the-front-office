"""Gemini AI client wrapper."""

import logging
from typing import TYPE_CHECKING, TypeVar

from google import genai
from google.genai.chats import Chat
from pydantic import BaseModel

from the_front_office.config.settings import settings
from the_front_office.exceptions import AIResponseError, AIUnavailableError

from .constants import MODEL_FLASH, MODEL_PRO
from .types import HistoryItem, MockChatSession

if TYPE_CHECKING:
    from the_front_office.trade.types import TradeProposal

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


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

    def generate_structured(self, prompt: str, schema: type[TModel], mock: TModel | None = None) -> TModel:
        """Generate a response conforming to `schema`.

        Uses Gemini's response-schema mode rather than asking for a format in
        prose, so a model that ignores the requested shape fails loudly here
        instead of producing a report the UI cannot render.

        Note: response schemas and the Google Search tool are mutually exclusive
        in the Gemini API, which is why the trade path keeps search and converts
        its prose afterwards (see structure_text).

        Raises:
            AIUnavailableError: no credentials.
            AIResponseError: the call failed, or returned nothing parseable.
        """
        if self.mock_mode:
            if mock is None:
                raise AIResponseError(f"Mock mode has no canned {schema.__name__}.")
            return mock

        if not self.client:
            raise AIUnavailableError()

        try:
            response = self.client.models.generate_content(
                model=MODEL_PRO,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": schema},
            )
        except Exception as e:
            logger.error(f"Structured generation failed: {e}")
            raise AIResponseError(f"Gemini call failed: {e}") from e

        return self._parsed_or_raise(response, schema)

    def structure_text(self, text: str, schema: type[TModel], instruction: str, mock: TModel | None = None) -> TModel:
        """Convert prose the model already produced into `schema`, using Flash.

        The trade path needs Google Search for live injury and standings data,
        and search cannot be combined with a response schema. Rather than give
        up one or the other, the search-grounded prose is structured in a second,
        cheap pass — the same Flash-for-parsing split parse_trade_string uses.
        """
        if self.mock_mode:
            if mock is None:
                raise AIResponseError(f"Mock mode has no canned {schema.__name__}.")
            return mock

        if not self.client:
            raise AIUnavailableError()

        prompt = (
            f"{instruction}\n\nConvert the following analysis verbatim — do not add, drop or soften anything:\n\n{text}"
        )
        try:
            response = self.client.models.generate_content(
                model=MODEL_FLASH,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": schema},
            )
        except Exception as e:
            logger.error(f"Structuring failed: {e}")
            raise AIResponseError(f"Could not structure the AI response: {e}") from e

        return self._parsed_or_raise(response, schema)

    @staticmethod
    def _parsed_or_raise(response: object, schema: type[TModel]) -> TModel:
        """Pull the validated model off a genai response, or raise."""
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed

        # genai populates .parsed for schema responses; fall back to the raw
        # JSON so a client-library change degrades to a parse rather than a crash.
        raw = getattr(response, "text", None)
        if raw:
            try:
                return schema.model_validate_json(raw)
            except Exception as e:
                logger.error(f"Response did not match {schema.__name__}: {e}")
                raise AIResponseError(f"Gemini returned a {schema.__name__} that failed validation.") from e
        raise AIResponseError(f"Gemini returned no usable {schema.__name__}.")

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
