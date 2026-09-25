"""
One-off check against the real Vercel AI Gateway (costs one tiny Jev call with --smoke).

    python scripts/check_jev_models.py            # list evaluation models, look for a versioned Jev id
    python scripts/check_jev_models.py --smoke    # also send one Choice with a JSON-object state

Prints model ids, answers, usage, and cost. Never prints the API key.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.decisions.base import JevDecisionError
from app.decisions.jev_client import JevClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="also make one real systemone call")
    args = parser.parse_args()

    if not settings.AI_GATEWAY_API_KEY:
        sys.exit("AI_GATEWAY_API_KEY is not set in .env")

    client = JevClient(settings.AI_GATEWAY_API_KEY, settings.JEV_BASE_URL, settings.JEV_MODEL, settings.JEV_TIMEOUT_SECONDS)

    # Observed shape (25 Sept 2026): {"models": [{"name": "jev", "description": ..., "release_date": ...}]}
    models = client.list_models().get("models", [])
    print(f"{len(models)} models listed")
    for m in models:
        print(f"  name={m.get('name')} release_date={m.get('release_date')}")
    print("configured JEV_MODEL:", settings.JEV_MODEL)
    print("A versioned id would look like jev-YYYY-MM-DD or jev@1; if none is listed, the model is unpinned.")

    if args.smoke:
        try:
            r = client.ask(
                state={"question": "What is the capital of France?"},
                questions={"route": {
                    "type": "choice",
                    "instructions": "Where should this question be answered from?",
                    "criteria": {"vectorstore": "Needs our uploaded documents", "web": "Needs live or recent information", "direct": "General knowledge, no lookup needed"},
                }},
            )
        except JevDecisionError as e:
            sys.exit(f"smoke call failed: {e.reason} {e.detail}")
        print("smoke answers:", json.dumps(r.answers))
        print(f"smoke model={r.model} latency_ms={r.latency_ms} input_tokens={r.input_tokens} output_tokens={r.output_tokens} cost={r.cost_usd} market_cost={r.market_cost_usd}")


if __name__ == "__main__":
    main()
