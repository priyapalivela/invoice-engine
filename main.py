"""
Invoice Extraction Engine
Usage:
    python main.py samples/invoice1.png
    python main.py path/to/invoice.pdf
    python main.py                         # runs all files in samples/
"""

import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from extractor import extract_invoice

load_dotenv()  # loads ANTHROPIC_API_KEY from .env


def print_result(result: dict) -> None:
    """Pretty-print the extracted invoice data."""
    print(json.dumps(result, indent=2))

    conf = result.get("confidence", {})
    level = conf.get("overall", "unknown")
    flagged = conf.get("flagged_fields", [])

    symbol = {"high": "✓", "medium": "~", "low": "!"}.get(level, "?")
    print(f"\n[{symbol}] Confidence: {level.upper()}")
    if flagged:
        print(f"    Flagged fields: {', '.join(flagged)}")


def run_file(file_path: str) -> None:
    path = Path(file_path)
    print(f"\n{'─' * 50}")
    print(f"  Extracting: {path.name}")
    print(f"{'─' * 50}")
    try:
        result = extract_invoice(file_path)
        print_result(result)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
    except ValueError as e:
        print(f"[ERROR] {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")


def main() -> None:
    args = sys.argv[1:]

    if args:
        for file_path in args:
            run_file(file_path)
    else:
        # No args — process everything in samples/
        samples_dir = Path("samples")
        if not samples_dir.exists():
            print("No file specified and no samples/ directory found.")
            print("Usage: python main.py path/to/invoice.pdf")
            sys.exit(1)

        files = sorted(
            f for f in samples_dir.iterdir()
            if f.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
        )
        if not files:
            print("No invoice files found in samples/")
            sys.exit(1)

        print(f"Found {len(files)} file(s) in samples/ — extracting all...\n")
        for f in files:
            run_file(str(f))


if __name__ == "__main__":
    main()
