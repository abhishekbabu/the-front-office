"""
Gemini AI Client wrapper.
"""
import logging
from typing import Optional
from google import genai
from the_front_office.config.settings import GEMINI_API_KEY, DEFAULT_MODEL

logger = logging.getLogger(__name__)

class GeminiClient:
    def __init__(self, api_key: Optional[str] = GEMINI_API_KEY, model: str = DEFAULT_MODEL):
        self.model = model
        if not api_key:
            logger.warning("GOOGLE_API_KEY not found. AI features will be disabled.")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)

    def generate(self, prompt: str) -> str:
        """
        Generate content using the Gemini model.
        """
        if not self.client:
            return "⚠️ AI Features Unavailable: API key not set."
            
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            return response.text or "❌ No response from AI"
        except Exception as e:
            logger.error(f"Gemini generation error: {e}")
            return f"❌ Error generating AI response: {e}"
