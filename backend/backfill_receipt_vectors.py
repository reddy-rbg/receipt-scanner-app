"""Backfill receipt_items and receipt_item_embeddings from existing receipts.

Run from the backend folder after supabase_agent_ml.sql has been applied:
    python backfill_receipt_vectors.py
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent.parent / "BS" / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill local receipt vector rows.")
    parser.add_argument("--user-id", help="Backfill one authenticated user's receipts.")
    parser.add_argument("--guest-session-id", help="Backfill one guest session's receipts.")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum receipts to scan.")
    args = parser.parse_args()

    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"):
        print("Missing SUPABASE_URL or SUPABASE_KEY in backend/.env or environment.", file=sys.stderr)
        return 2

    from app.services.database import backfill_receipt_vectors

    result = backfill_receipt_vectors(
        user_id=args.user_id,
        guest_session_id=args.guest_session_id,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
