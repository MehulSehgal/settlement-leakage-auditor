"""
Settlement Leakage Auditor — CLI entrypoint.
Runs the full pipeline once and writes dashboard_payload.json to disk.
For live/repeated runs (used by the dashboard), see api.py instead.
"""
import json
from pipeline_runner import run_full_pipeline, DB_PATH


def main():
    payload = run_full_pipeline(DB_PATH)
    with open("dashboard_payload.json", "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(json.dumps(payload["summary"], indent=2))
    print(json.dumps(payload["evaluation"], indent=2))
    print(f"\nExported dashboard_payload.json ({len(payload['exception_queue'])} exceptions, "
          f"{len(payload['showcase_cases'])} showcase cases)")


if __name__ == "__main__":
    main()
