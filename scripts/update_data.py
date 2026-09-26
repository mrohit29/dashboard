"""
Entry point for the GitHub Actions refresh job.

This first version intentionally writes the dashboard's expected data files from
source-specific collectors. Add/replace collectors only where public official
endpoints/files are reliable; do not invent weekly sector-FPI values.
"""
from pathlib import Path
import json
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"

def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

def main():
    # Placeholder until the official-source collectors are wired in.
    # Keeping this script executable makes the CI pipeline easy to validate.
    meta = json.loads((DATA/"weekly.json").read_text(encoding="utf-8"))
    meta["meta"]["last_checked_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(DATA/"weekly.json", meta)
    print("Refresh skeleton completed. Live collectors are not enabled yet.")

if __name__ == "__main__":
    main()
