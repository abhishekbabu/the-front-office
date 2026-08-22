"""Gemini's implementation of the AnalysisModel port."""

import logging
import time

from google import genai
from google.genai.chats import Chat

from the_front_office.config.settings import settings
from the_front_office.domain.errors import AIResponseError, AIUnavailableError
from the_front_office.domain.models import TradeProposal
from the_front_office.domain.ports import AnalysisModel, ChatSession, HistoryTurn, TModel

from .constants import MODEL_FLASH, MODEL_PRO
from .types import MockChatSession

logger = logging.getLogger(__name__)

# The TypeVar the port declares, so the override types match exactly.


class GeminiClient(AnalysisModel):
    """Gemini's implementation of the AnalysisModel port.

    Inherits the protocol explicitly rather than matching it structurally, so
    the type checker fails here — at the adapter — if the two ever drift apart,
    instead of at whichever caller happens to notice first.
    """

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

    @staticmethod
    def _log_usage(model: str, response: object, elapsed: float) -> None:
        """Record what a call cost.

        Gemini Pro on a large prompt is the only real expense here, and nothing
        else measures it — without this there is no way to answer "what does a
        scout report cost?" from production logs.
        """
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            logger.info(f"{model} responded in {elapsed:.2f}s (no usage metadata)")
            return
        prompt_tokens = getattr(usage, "prompt_token_count", None)
        output_tokens = getattr(usage, "candidates_token_count", None)
        total = getattr(usage, "total_token_count", None)
        cached = getattr(usage, "cached_content_token_count", None)
        logger.info(
            f"{model} responded in {elapsed:.2f}s — "
            f"{prompt_tokens} in, {output_tokens} out, {total} total" + (f", {cached} cached" if cached else "")
        )

    # pyrefly: ignore[bad-override]  — the port and this method have byte-identical
    # signatures (verified by inspect.signature and isinstance at runtime); pyrefly
    # cannot prove two generic method types equivalent across modules.
    def generate_structured(self, prompt: str, schema: type[TModel], mock: TModel | None = None) -> TModel:
        """Generate a response conforming to `schema`.

        Uses response-schema mode rather than asking for a format in prose, so a
        model that ignores the shape fails here instead of producing something
        unrenderable.

        A response schema cannot be combined with the Google Search tool; see
        `structure_text` for the path that needs both.

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
            started = time.perf_counter()
            response = self.client.models.generate_content(
                model=MODEL_PRO,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": schema},
            )
            self._log_usage(MODEL_PRO, response, time.perf_counter() - started)
        except Exception as e:
            logger.error(f"Structured generation failed: {e}")
            raise AIResponseError(f"Gemini call failed: {e}") from e

        return self._parsed_or_raise(response, schema)

    # pyrefly: ignore[bad-override]  — the port and this method have byte-identical
    # signatures (verified by inspect.signature and isinstance at runtime); pyrefly
    # cannot prove two generic method types equivalent across modules.
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
            started = time.perf_counter()
            response = self.client.models.generate_content(
                model=MODEL_FLASH,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": schema},
            )
            self._log_usage(MODEL_FLASH, response, time.perf_counter() - started)
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

    def start_chat(self, initial_history: list[HistoryTurn] | None = None, enable_search: bool = False) -> ChatSession:
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

        return self.client.chats.create(
            model=MODEL_PRO,
            history=initial_history,  # type: ignore[arg-type]
            config=config,
        )

    def parse_trade_string(self, text: str) -> TradeProposal:
        """
        Parse a natural language trade string into a structured TradeProposal.
        Uses Gemini Flash for speed and cost efficiency.
        """

        if self.mock_mode:
            return TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])

        if not self.client:
            raise AIUnavailableError()

        prompt = f"""
        Extract the players being given and received in this trade offer.
        Return ONLY a JSON object with keys "giving" and "receiving".
        Using full player names.

        Trade: "{text}"
        """

        try:
            started = time.perf_counter()
            response = self.client.models.generate_content(
                model=MODEL_FLASH, contents=prompt, config={"response_mime_type": "application/json"}
            )
            self._log_usage(MODEL_FLASH, response, time.perf_counter() - started)

            import json

            text = response.text or "{}"
            data = json.loads(text)
            # The model returns a bare string when only one player is involved.
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
