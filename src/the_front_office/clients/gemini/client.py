"""
Gemini AI Client wrapper.
"""
import logging
from typing import Optional
from google import genai
from the_front_office.config.settings import GEMINI_API_KEY, DEFAULT_MODEL

logger = logging.getLogger(__name__)

class GeminiClient:
    def __init__(self, api_key: Optional[str] = GEMINI_API_KEY, model: str = DEFAULT_MODEL, mock_mode: bool = False):
        self.model = model
        self.mock_mode = mock_mode
        
        if self.mock_mode:
            logger.debug("🎭 Mock AI mode enabled - using canned responses")
            self.client = None
        elif not api_key:
            logger.warning("GOOGLE_API_KEY not found. AI features will be disabled.")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)

    def generate(self, prompt: str) -> str:
        """
        Generate content using the Gemini model (or return mock response).
        """
        if self.mock_mode:
            return self._get_mock_response()
        
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
    
    def _get_mock_response(self) -> str:
        """Return a canned mock response for testing."""
        return """### **Scout Report**

**Matchup Insight**: [MOCK] We are positioned for a 6-3 victory. Focus on securing REB and protecting our FG% lead.

**Top Targets**:
- **ADD Mock Player 1 (PF)**: [MOCK] Provides elite rebounding and efficient shooting. -> **DROP Bench Warmer**: Minimal production.
- **ADD Mock Player 2 (C)**: [MOCK] Strong blocks and rebounds contributor. -> **DROP Injured Reserve**: Currently out.
- **ADD Mock Player 3 (SG)**: [MOCK] High-volume 3PT shooter to secure our lead. -> **DROP Inconsistent Guard**: Poor recent performance.

**Final Strategy**: [MOCK] Add efficient, multi-category contributors to secure the win."""
