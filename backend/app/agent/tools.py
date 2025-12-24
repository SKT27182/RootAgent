"""
Agent tools that are passed to the executor as additional functions.
These functions are available to the LLM during code execution.
"""

from __future__ import annotations
import io
import base64
from typing import Any, List, Optional
from pydantic import BaseModel, HttpUrl

from urllib.parse import urlparse
from tavily import TavilyClient
from backend.app.core.config import Config

## Figure to Base64 Tool


def figure_to_base64(fig: Any) -> str:
    """
    Convert a matplotlib figure to a base64-encoded PNG string.

    Args:
        fig: A matplotlib figure object (e.g., from plt.gcf() or plt.figure())

    Returns:
        A base64-encoded string of the PNG image.

    Example usage in LLM code:
        import matplotlib.pyplot as plt
        plt.plot([1, 2, 3], [4, 5, 6])
        result = figure_to_base64(plt.gcf())
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode("utf-8")
    buf.close()
    return f"![Generated Image](data:image/png;base64,{img_base64})"


## Web Search Tool


def get_base_domain(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Remove common subdomains
    if hostname.startswith("www."):
        hostname = hostname[4:]

    return hostname


class TavilySearchResult(BaseModel):
    title: str
    source: str
    content: Optional[str] = None
    score: Optional[float] = None


class TavilyWebSearch:
    """
    Web search using Tavily API.
    Supports:
    - fresh results
    - full page content
    - domain filtering
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_results: int = 5,
        search_depth: str = "basic",  # "basic" | "advanced"
        include_content: bool = True,
    ):
        self.client = TavilyClient(api_key=api_key)
        self.max_results = max_results
        self.search_depth = search_depth
        self.include_content = include_content

    def search(
        self,
        query: str,
        domains: Optional[List[str]] = None,
        recency_days: Optional[int] = None,
    ) -> List[TavilySearchResult]:
        """
        Perform web search and optionally retrieve full content.
        """

        response = self.client.search(
            query=query,
            max_results=self.max_results,
            search_depth=self.search_depth,
            include_answer=False,
            include_raw_content=self.include_content,
            domains=domains,
            recency_days=recency_days,
        )

        results: List[Dict[str, Any]] = []

        for r in response.get("results", []):
            results.append(
                {
                    "title": r.get("title"),
                    "source": get_base_domain(r.get("url")),
                    "url": r.get("url"),
                    "content": r.get("content"),
                    "score": r.get("score"),
                }
            )

        return results


def web_search(query: str, recency_days: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    STRICT WEB SEARCH TOOL — INFORMATION RETRIEVAL ONLY

    This function performs a web search and may optionally retrieve full webpage content.

    USAGE OF THIS TOOL IS STRICTLY LIMITED.
    Any misuse is considered a tool-selection error.

    YOU MUST USE THIS TOOL IF AND ONLY IF ALL OF THE FOLLOWING ARE TRUE:
    1. The question explicitly requires up-to-date, real-world, or external information
    2. The information CANNOT be reliably answered using reasoning alone
    3. The information is NOT part of the model’s static or general knowledge
    4. The answer depends on facts that may change over time (e.g., news, leadership, prices, releases)
    5. You are prepared to wait for the tool output BEFORE generating a final response

    YOU MUST NOT USE THIS TOOL UNDER ANY CIRCUMSTANCES IF:
    - The task can be solved via logic, reasoning, math, or deduction
    - The task involves programming (writing, debugging, reviewing, or explaining code)
    - The task is algorithmic, procedural, or computational
    - The answer is deterministic or universally known
    - The user asks for explanations, tutorials, summaries, or conceptual knowledge
    - The user provides all required information directly in the prompt
    - The task involves creative writing, ideation, or opinion
    - The task can be completed using internal model knowledge alone

    CRITICAL EXECUTION RULES:
    - This tool MUST be called before answering, not after
    - Do NOT partially answer before receiving tool output
    - Do NOT fabricate or infer missing facts without tool results
    - Do NOT combine this tool with reasoning-only answers
    - If the tool returns no useful data, state that explicitly

    ARGS:
        query (str):
            A precise, factual search query.
            Must target external, real-world information.
            Vague or exploratory queries are not allowed.

        recency_days (Optional[int]):
            Filters results to sources published within the specified number of days.
            Use ONLY when freshness is required.

    RETURNS:
        List[Dict], where each dictionary contains:
            - title (str): Source title
            - source (str): Publisher or domain
            - url (str): Source URL
            - content (str): Extracted relevant text
            - score (float): Relevance score

    VALID USE CASES (NON-EXHAUSTIVE):
    - Current CEO / leadership of a company
    - Recent policy changes or government announcements
    - Breaking or recent news events
    - Latest product releases or pricing
    - Recent research publications or reports

    INVALID USE CASES (NON-EXHAUSTIVE):
    - Writing or reviewing code
    - Solving equations or math problems
    - Explaining algorithms or concepts
    - Generating Dockerfiles or configs
    - Summarizing text already provided
    - Answering “how does X work” questions
    """

    search = TavilyWebSearch(max_results=5, api_key=Config.TAVILY_API_KEY)
    results = search.search(query, recency_days=recency_days)

    return results


# Dictionary of all tools to pass to the agent
AGENT_TOOLS = {
    "figure_to_base64": figure_to_base64,
    "web_search": web_search,
}
