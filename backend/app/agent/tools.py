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
    return img_base64


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
    Perform web search and optionally retrieve full content.

    THIS TOOL IS FOR INFORMATION RETRIEVAL ONLY.

    You MUST use this tool only when:
    - The question requires up-to-date, real-world, or external information
    - The information cannot be derived from reasoning alone
    - The information is not available in the model's static knowledge

    DO NOT use this tool when:
    - The question can be solved using logic, reasoning, math, or code
    - The task involves calculations, simulations, or algorithmic steps
    - The task is programming-related (writing, debugging, or explaining code)
    - The answer is deterministic and does not require external sources

    Args:
        query: The web search query.
        recency_days: Optional number of days to filter results by.

    Returns:
        List of Dicts with keys:
            - title: Title of the source
            - source: Source domain or publisher
            - url: URL of the source
            - content: Extracted relevant content
            - score: Relevance score

    Examples of VALID usage:
        - "What are the latest developments in AI research?"
        - "Recent news about OpenAI"
        - "Current CEO of Microsoft"

    Examples of INVALID usage:
        - "Write Python code to sort a list"
        - "Solve 2x + 3 = 7"
        - "Explain how quicksort works"
        - "Generate a Dockerfile"
    """

    search = TavilyWebSearch(max_results=5, api_key=Config.TAVILY_API_KEY)
    results = search.search(query, recency_days=recency_days)

    return results


# Dictionary of all tools to pass to the agent
AGENT_TOOLS = {
    "figure_to_base64": figure_to_base64,
    "web_search": web_search,
}
