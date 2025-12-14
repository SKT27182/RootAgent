"""
Agent tools that are passed to the executor as additional functions.
These functions are available to the LLM during code execution.
"""

import io
import base64
from typing import Any


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


# Dictionary of all tools to pass to the agent
AGENT_TOOLS = {
    "figure_to_base64": figure_to_base64,
}
