"""Run the offline job review workflow from any current directory."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper_framework.job_workflow.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
