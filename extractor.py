from dotenv import load_dotenv
load_dotenv() 

import os
import json
import anthropic
from prompts import SYSTEM_PROMPT, USER_PROMPT
from file_handler import load_file, build_content_block

MODEL = "claude-opus-4-5"


def extract_invoice(file_path: str) -> dict:
    """
    Send an invoice file to Claude and return the extracted data as a dict.

    Args:
        file_path: Path to the invoice file (PDF or image).

    Returns:
        Parsed JSON dict matching the invoice schema.

    Raises:
        FileNotFoundError, ValueError: from file_handler
        anthropic.APIError: on API failures
        json.JSONDecodeError: if the model returns malformed JSON
    """
    base64_data, media_type = load_file(file_path)
    file_block = build_content_block(base64_data, media_type)

    #client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env automatically
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    file_block,
                    {"type": "text", "text": USER_PROMPT},
                ],
            }
        ],
    )

    raw_text = response.content[0].text.strip()

    # Strip accidental markdown fences (defensive — model should never add them)
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    return json.loads(raw_text)
