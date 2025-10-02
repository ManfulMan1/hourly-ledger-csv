# hourly-ledger-csv

Hourly time ledger in **CSV**: each run appends one row per day (UTC timestamp, local zones for Kyiv/NY, ISO week, weekday/hour flags, month/quarter markers, checksum).  
Stdlib-only, no external APIs. Runs every hour at `00` (UTC) via GitHub Actions.

- Folder per day: `data/YYYY-MM-DD/hourly.csv`
- Safe to diff; stable cadence for repository activity.
