"""
Groq API integration for Savify summarization.
Uses OpenAI-compatible chat completions endpoint with openai/gpt-oss-120b.
"""

import os
import json
import re as _re

import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

API_KEY = os.getenv("GROQ_API_KEY")
if not API_KEY:
    raise EnvironmentError(
        "GROQ_API_KEY environment variable is not set. "
        "Create a .env file in the backend/ directory with:\n"
        "GROQ_API_KEY=your_api_key_here\n"
        "Get a free key at https://console.groq.com/keys"
    )

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "openai/gpt-oss-120b"
REQUEST_TIMEOUT = 60  # seconds

SUMMARIZATION_PROMPT = """You are an expert blog summarizer. Analyze the following blog article and return a structured JSON summary.

IMPORTANT: Return ONLY valid JSON, no markdown, no code fences, no extra text.

The JSON must have exactly these fields:
{{
    "title": "A clear, concise title for the article",
    "summary": "A comprehensive 2-3 sentence summary of the article's main message",
    "key_points": ["Point 1", "Point 2", "Point 3", "Point 4", "Point 5"],
    "difficulty": "Beginner OR Intermediate OR Advanced",
    "category": "AI OR Web Dev OR ML OR Cybersecurity OR General",
    "takeaway": "The single most important actionable takeaway from this article"
}}

Rules:
- "title": If the article has a clear title, use it. Otherwise, create a descriptive one.
- "summary": Capture the core message in 2-3 clear sentences.
- "key_points": Extract exactly 5 key points. Each should be a concise, standalone insight.
- "difficulty": Rate based on the technical depth and assumed reader knowledge.
- "category": Choose the most relevant tag. Use "General" if none of the others fit strictly.
- "takeaway": One actionable sentence the reader should remember.

ARTICLE TEXT:
{article_text}
"""

YOUTUBE_SUMMARIZATION_PROMPT = """You are an expert video content summarizer. Analyze the following YouTube video transcript and return a structured JSON summary.

IMPORTANT: Return ONLY valid JSON, no markdown, no code fences, no extra text.

The JSON must have exactly these fields:
{{
    "title": "A clear, concise title for the video",
    "summary": "A comprehensive 2-3 sentence summary of the video's main message",
    "key_points": ["Insight 1", "Insight 2", "Insight 3", "Insight 4", "Insight 5"],
    "difficulty": "Beginner OR Intermediate OR Advanced",
    "takeaway": "The single most important actionable takeaway from this video",
    "tools_mentioned": ["Tool or resource 1", "Tool or resource 2"],
    "category": "AI OR Web Dev OR ML OR Cybersecurity OR General"
}}

Rules:
- "title": Create a clear, descriptive title for the video content.
- "summary": Capture the core message in 2-3 clear sentences.
- "key_points": Extract exactly 5 key insights. Each should be a concise, standalone point.
- "difficulty": Rate based on the technical depth and assumed viewer knowledge.
- "takeaway": One actionable sentence the viewer should remember.
- "tools_mentioned": List any tools, libraries, frameworks, services, or resources mentioned. Use an empty list [] if none.
- "category": Choose the most relevant tag. Use "General" if none of the others fit strictly.

VIDEO TRANSCRIPT:
{transcript_text}
"""


def _parse_json_robust(text: str) -> dict:
    """
    Attempt to parse JSON with multiple recovery strategies:
    1. Direct parse
    2. Auto-close truncated brackets/braces
    3. Regex field extraction as last resort
    """
    # Strategy 1 & 2: Try parsing direct or repaired JSON
    parsed_dict = None
    try:
        parsed_dict = json.loads(text)
    except json.JSONDecodeError:
        # Auto-close truncated JSON
        repaired = text.rstrip().rstrip(",")
        open_braces = repaired.count("{") - repaired.count("}")
        open_brackets = repaired.count("[") - repaired.count("]")

        quote_count = repaired.count('"')
        if quote_count % 2 != 0:
            repaired += '"'

        repaired += "]" * max(0, open_brackets)
        repaired += "}" * max(0, open_braces)

        try:
            parsed_dict = json.loads(repaired)
        except json.JSONDecodeError:
            pass

    # Strategy 3: Regex extraction of known fields
    def _extract(field_name: str, fallback=""):
        pattern = rf'"{field_name}"\s*:\s*"((?:[^"\\]|\\.)*)'
        m = _re.search(pattern, text, _re.DOTALL)
        return m.group(1).rstrip('"').replace('\\"', '"') if m else fallback

    def _extract_list(field_name: str):
        pattern = rf'"{field_name}"\s*:\s*\[(.*)(?:\]|$)'
        m = _re.search(pattern, text, _re.DOTALL)
        if m:
            items = _re.findall(r'"((?:[^"\\]|\\.)*)', m.group(1))
            return [item.rstrip('"') for item in items if item]
        return []

    if parsed_dict is None:
        # Use entirely regex if JSON parsing completely failed
        result = {
            "title": _extract("title", "Untitled"),
            "summary": _extract("summary", text[:300]),
            "key_points": _extract_list("key_points") or ["See summary above"],
            "difficulty": _extract("difficulty", "Intermediate"),
            "category": _extract("category", "General"),
            "takeaway": _extract("takeaway", "See summary for details."),
            "tools_mentioned": _extract_list("tools_mentioned"),
        }
    else:
        # JSON parsed successfully (perhaps repaired), but might be missing fields due to truncation
        result = parsed_dict
        if "title" not in result: result["title"] = _extract("title", "Untitled")
        if "summary" not in result: result["summary"] = _extract("summary", text[:300])
        if "key_points" not in result: result["key_points"] = _extract_list("key_points") or ["See summary above"]
        if "difficulty" not in result: result["difficulty"] = _extract("difficulty", "Intermediate")
        if "category" not in result: result["category"] = _extract("category", "General")
        if "takeaway" not in result: result["takeaway"] = _extract("takeaway", "See summary for details.")
        if "tools_mentioned" not in result: result["tools_mentioned"] = _extract_list("tools_mentioned")

    # Validate we got at least a title or summary or key points
    if result["title"] == "Untitled" and result["summary"] == text[:300] and result.get("key_points") == ["See summary above"]:
        raise RuntimeError(
            f"LLM returned unparseable response:\n{text[:500]}"
        )

    return result


def _call_llm(prompt: str) -> dict:
    """
    Send a prompt to Groq and parse the JSON response.
    Shared by both blog and YouTube summarization.
    """
    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_completion_tokens": 2048,
                "reasoning_effort": "low",
                "response_format": {"type": "json_object"},
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 401:
            raise RuntimeError("Invalid Groq API key. Please check your GROQ_API_KEY.")
        if response.status_code == 429:
            raise RuntimeError("Groq rate limit hit. Wait a moment and try again.")
        if response.status_code != 200:
            detail = response.text[:300]
            raise RuntimeError(f"Groq API error {response.status_code}: {detail}")

        response_text = response.json()["choices"][0]["message"]["content"].strip()

        # Clean potential markdown code fences
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            response_text = "\n".join(lines).strip()

        # Parse JSON — with robust recovery for truncated responses
        return _parse_json_robust(response_text)

    except requests.exceptions.Timeout:
        raise RuntimeError(f"Groq API request timed out after {REQUEST_TIMEOUT}s.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to Groq API. Check your internet connection.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Groq API error: {str(e)}")


def summarize_text(text: str) -> dict:
    """
    Send article text to Groq and get a structured summary.

    Returns:
        dict with keys: title, summary, key_points, difficulty, category, takeaway
    """
    prompt = SUMMARIZATION_PROMPT.format(article_text=text)
    result = _call_llm(prompt)

    # Validate required fields
    required_fields = ["title", "summary", "key_points", "difficulty", "category", "takeaway"]
    for field in required_fields:
        if field not in result:
            raise RuntimeError(f"LLM response missing required field: {field}")

    # Ensure key_points is a list
    if not isinstance(result["key_points"], list):
        result["key_points"] = [result["key_points"]]

    # Validate difficulty and category
    valid_difficulties = ["Beginner", "Intermediate", "Advanced"]
    if result["difficulty"] not in valid_difficulties:
        result["difficulty"] = "Intermediate"

    valid_categories = ["AI", "Web Dev", "ML", "Cybersecurity", "General"]
    if result["category"] not in valid_categories:
        result["category"] = "General"

    return result


def summarize_youtube(transcript_text: str) -> dict:
    """
    Send video transcript to Groq and get a structured summary.

    Returns:
        dict with keys: title, summary, key_points, difficulty, category, takeaway, tools_mentioned
    """
    prompt = YOUTUBE_SUMMARIZATION_PROMPT.format(transcript_text=transcript_text)
    result = _call_llm(prompt)

    # Validate required fields
    required_fields = ["title", "summary", "key_points", "difficulty", "category", "takeaway"]
    for field in required_fields:
        if field not in result:
            raise RuntimeError(f"LLM response missing required field: {field}")

    # Ensure key_points is a list
    if not isinstance(result["key_points"], list):
        result["key_points"] = [result["key_points"]]

    # Ensure tools_mentioned is a list (optional field)
    if "tools_mentioned" not in result:
        result["tools_mentioned"] = []
    if not isinstance(result["tools_mentioned"], list):
        result["tools_mentioned"] = [result["tools_mentioned"]]

    # Validate difficulty and category
    valid_difficulties = ["Beginner", "Intermediate", "Advanced"]
    if result["difficulty"] not in valid_difficulties:
        result["difficulty"] = "Intermediate"

    valid_categories = ["AI", "Web Dev", "ML", "Cybersecurity", "General"]
    if result["category"] not in valid_categories:
        result["category"] = "General"

    return result
