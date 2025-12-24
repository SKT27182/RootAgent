import os
import uuid
import tempfile
from typing import List, Dict, Optional

# Use system temp directory for uploaded CSV files (auto-cleaned by OS)
DATA_DIR = tempfile.gettempdir()


def format_user_message(
    query: str, images: Optional[List[str]] = None, csv_data: Optional[str] = None
) -> List[Dict]:
    """
    Formats the user message into the structure expected by the LLM.
    Handles text, images, and CSV data.
    """
    user_content = [{"type": "text", "text": query}]

    if images:
        for img_str in images:
            if not img_str.startswith("data:image"):
                url = f"data:image/jpeg;base64,{img_str}"
            else:
                url = img_str

            user_content.append({"type": "image_url", "image_url": {"url": url}})

    if csv_data:
        filename = f"data_{uuid.uuid4().hex[:8]}.csv"
        filepath = os.path.join(DATA_DIR, filename)

        try:
            with open(filepath, "w") as f:
                f.write(csv_data)

            user_content.append(
                {
                    "type": "text",
                    "text": f"\n\nI have provided a CSV file at '{filepath}' containing the data. You can write code to read and analyze it.",
                }
            )
        except Exception as e:
            # Fallback or log error? For now, just append the error text so the model knows something went wrong.
            user_content.append(
                {
                    "type": "text",
                    "text": f"\n\nFailed to save CSV file: {str(e)}",
                }
            )

    return user_content


def format_assistant_message(content: str) -> List[Dict]:
    """
    Formats the assistant message into a structured format.
    Detects base64 image data URIs and converts them to image_url type.
    Remaining text is preserved as text type.

    Args:
        content: The raw assistant message content (may contain markdown images)

    Returns:
        List of structured content parts (text and/or image_url types)
    """
    import re

    # Pattern to match markdown images with data URIs: ![...](data:image/...;base64,...)
    # Also matches standalone data URIs
    image_pattern = r"!\[([^\]]*)\]\((data:image\/[a-zA-Z]+;base64,[^\)]+)\)"

    result = []
    last_end = 0

    for match in re.finditer(image_pattern, content):
        # Add any text before this match
        text_before = content[last_end : match.start()].strip()
        if text_before:
            result.append({"type": "text", "text": text_before})

        # Add the image
        image_url = match.group(2)
        result.append({"type": "image_url", "image_url": {"url": image_url}})

        last_end = match.end()

    # Add any remaining text after the last match
    text_after = content[last_end:].strip()
    if text_after:
        result.append({"type": "text", "text": text_after})

    # If no images found, return the original content as text
    if not result:
        result.append({"type": "text", "text": content})

    return result
