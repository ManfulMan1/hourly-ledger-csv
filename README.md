# hourly-ledger-csv

Hourly time ledger in **CSV**: each run appends one row per day (UTC timestamp, local zones for Kyiv/NY, ISO week, weekday/hour flags, month/quarter markers, checksum).
Stdlib-only, no external APIs. Runs every hour at `00` (UTC) via GitHub Actions.

- Folder per day: `data/YYYY-MM-DD/hourly.csv`
- Safe to diff; stable cadence for repository activity.

## Row schema

| Column | Meaning |
|---|---|
| `ts_utc` | UTC timestamp, second precision (`2026-08-12T14:30:05+00:00`) |
| `unix` | Unix epoch seconds |
| `iso_week` | ISO-8601 week number (1–53) |
| `weekday` | ISO weekday, 1=Monday … 7=Sunday |
| `hour_utc` | Hour of the day in UTC (0–23) |
| `day_of_year` | Day of the year (1–366) |
| `month`, `quarter` | Calendar month and quarter (1–4) |
| `is_month_start` | 1 if the first day of the month, else 0 |
| `is_quarter_start` | 1 if the first day of a quarter (Jan/Apr/Jul/Oct 1st), else 0 |
| `kyiv` | Same instant in Kyiv local time |
| `new_york` | Same instant in New York local time |
| `checksum` | SHA-256 prefix (12 hex chars) over `ts_utc\|iso_week\|weekday\|day_of_year` |
| `format` | Ledger format version (`csv-ledger-v2`) |

## Timezones

Local times use the system IANA database via the stdlib `zoneinfo` module, so
offsets follow **real DST rules** — including Ukraine staying on UTC+2
year-round since it abolished seasonal clock changes in July 2024 (enforced
explicitly so results are correct even with an outdated tz database).
If the tz database is unavailable, a month-based approximation is used as a
fallback.

## Usage

```bash
# Append a row for the current hour
python3 scripts/update.py

# Preview the row without writing anything
python3 scripts/update.py --dry-run

# Append even if the current hour already has a row
python3 scripts/update.py --force

# Revalidate checksums across the whole ledger
python3 scripts/update.py --verify
```

The script is idempotent per hour: if the current hour already has a row, the
run is a no-op (exit 0) unless `--force` is given — so retried workflow runs
never produce duplicate rows. Rows written before the checksum scheme was
made reproducible (format `csv-ledger-v1`) are counted as *legacy* by
`--verify` rather than reported as mismatches.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Stdlib-only `unittest` — no dependencies to install.
