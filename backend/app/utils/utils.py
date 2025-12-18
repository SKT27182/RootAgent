import os
import uuid
import tempfile
from typing import List, Dict, Optional
from pathlib import Path

# Use system temp directory for uploaded CSV files (auto-cleaned by OS)
SHARED_TMP_DIR = Path(os.getenv("SHARED_TMP_DIR", "/tmp/shared"))


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
        filepath = os.path.join(SHARED_TMP_DIR, filename)

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
