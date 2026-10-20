"""Allow `python3 -m ingest` → build activity.json."""

from .build import main

raise SystemExit(main())
