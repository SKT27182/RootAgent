import os
import uuid
from typing import List, Dict, Optional

# Data directory for uploaded files
DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data"
)


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
        # Ensure data directory exists
        os.makedirs(DATA_DIR, exist_ok=True)

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
