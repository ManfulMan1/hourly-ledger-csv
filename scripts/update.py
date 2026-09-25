#!/usr/bin/env python3
"""Hourly CSV time-ledger appender.

Stdlib-only. Each run appends one row to ``data/YYYY-MM-DD/hourly.csv``
with the current UTC timestamp, Kyiv/NY local times, ISO week/day flags,
month/quarter markers, and a checksum that can be reproduced from the
stored row (``--verify`` revalidates the whole ledger).

Timezones come from the system IANA database via :mod:`zoneinfo`, so
offsets follow real DST rules (including Ukraine staying on UTC+2 since
it abolished seasonal clock changes in July 2024). If the tz database is
unavailable, a month-based approximation is used as a fallback.

CLI::

    python scripts/update.py              append row for the current hour
    python scripts/update.py --dry-run    print the row without writing
    python scripts/update.py --force      append even if the hour exists
    python scripts/update.py --verify     revalidate checksums of the ledger
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

try:
    from zoneinfo import ZoneInfo

    _KYIV = ZoneInfo("Europe/Kyiv")
    _NEW_YORK = ZoneInfo("America/New_York")
except (ImportError, ModuleNotFoundError):  # tz database not available
    _KYIV = None
    _NEW_YORK = None

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Bumped when the checksum input changed (v1 hashed microseconds that are
# not stored, so it could not be reproduced from the row itself).
FORMAT = "csv-ledger-v2"

HEADERS = [
    "ts_utc", "unix", "iso_week", "weekday", "hour_utc", "day_of_year",
    "month", "quarter", "is_month_start", "is_quarter_start",
    "kyiv", "new_york", "checksum", "format",
]


def _approx_offset(now_utc: datetime, zone: str) -> timezone:
    """Month-based DST approximation, used only when zoneinfo is missing."""
    if zone == "Europe/Kyiv":
        # Ukraine abolished seasonal clock changes in July 2024: UTC+2 flat.
        offset = 3 if 3 <= now_utc.month <= 10 and now_utc.year < 2025 else 2
        return timezone(timedelta(hours=offset), name=f"UTC+{offset}")
    offset = -4 if 3 <= now_utc.month <= 11 else -5  # approximate EDT/EST
    return timezone(timedelta(hours=offset), name=f"UTC{offset}")


def kyiv_local(now_utc: datetime) -> datetime:
    # Ukraine abolished seasonal clock changes on 2024-07-16 (law signed
    # 2024-07-15); since then Kyiv is UTC+2 year-round. Encode this
    # explicitly so the result is correct even with an outdated tz database.
    if now_utc >= datetime(2024, 7, 16, tzinfo=timezone.utc):
        return now_utc.astimezone(timezone(timedelta(hours=2), name="UTC+2"))
    if _KYIV is not None:
        return now_utc.astimezone(_KYIV)
    return now_utc.astimezone(_approx_offset(now_utc, "Europe/Kyiv"))


def ny_local(now_utc: datetime) -> datetime:
    if _NEW_YORK is not None:
        return now_utc.astimezone(_NEW_YORK)
    return now_utc.astimezone(_approx_offset(now_utc, "America/New_York"))


def checksum(ts_utc: str, iso_week: int, weekday: int, day_of_year: int) -> str:
    """SHA-256 prefix over the stored fields, reproducible from the row."""
    raw = f"{ts_utc}|{iso_week}|{weekday}|{day_of_year}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def build_row(now_utc: Optional[datetime] = None) -> Dict[str, object]:
    """Build the ledger row for *now_utc* (defaults to the current time)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    kyiv = kyiv_local(now_utc)
    ny = ny_local(now_utc)

    iso_year, iso_week, weekday = now_utc.isocalendar()
    day_of_year = now_utc.timetuple().tm_yday
    month = now_utc.month
    quarter = (month - 1) // 3 + 1

    ts_utc = now_utc.isoformat(timespec="seconds")
    return {
        "ts_utc": ts_utc,
        "unix": int(now_utc.timestamp()),
        "iso_week": iso_week,
        "weekday": weekday,  # 1..7 (Monday=1)
        "hour_utc": now_utc.hour,
        "day_of_year": day_of_year,
        "month": month,
        "quarter": quarter,
        "is_month_start": 1 if now_utc.day == 1 else 0,
        "is_quarter_start": 1 if (month in (1, 4, 7, 10) and now_utc.day == 1) else 0,
        "kyiv": kyiv.isoformat(timespec="seconds"),
        "new_york": ny.isoformat(timespec="seconds"),
        "checksum": checksum(ts_utc, iso_week, weekday, day_of_year),
        "format": FORMAT,
    }


def hour_exists(data_dir: Path, now_utc: datetime) -> bool:
    """True if the current hour already has a row in the day's ledger."""
    outfile = data_dir / now_utc.strftime("%Y-%m-%d") / "hourly.csv"
    if not outfile.exists():
        return False
    with outfile.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("hour_utc") == str(now_utc.hour):
                return True
    return False


def append_row(
    data_dir: Path,
    now_utc: Optional[datetime] = None,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Append a row; return 0=appended, 1=skipped (hour exists), 2=error."""
    now_utc = now_utc or datetime.now(timezone.utc)
    day_dir = data_dir / now_utc.strftime("%Y-%m-%d")

    if not dry_run and not force and hour_exists(data_dir, now_utc):
        print(f"[update.py] hour {now_utc.hour:02d} already recorded -> skipped (use --force)")
        return 0  # successful no-op; the workflow diff-guard skips the commit

    row = build_row(now_utc)

    if dry_run:
        print(f"[update.py] dry-run row for {day_dir.name}:")
        for key in HEADERS:
            print(f"  {key:16s} {row[key]}")
        return 0

    day_dir.mkdir(parents=True, exist_ok=True)
    outfile = day_dir / "hourly.csv"
    file_exists = outfile.exists()
    with outfile.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    try:
        shown = outfile.relative_to(ROOT)
    except ValueError:  # outfile outside the repo (e.g. tests with tmp dirs)
        shown = outfile
    print(f"[update.py] appended row -> {shown}")
    return 0

def verify_ledger(data_dir: Path) -> int:
    """Recompute checksums over the whole ledger; return 1 on mismatch."""
    total = legacy = ok = bad = 0
    bad_rows = []
    for csv_path in sorted(data_dir.glob("*/*.csv")):
        with csv_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                total += 1
                if row.get("format") != FORMAT:
                    legacy += 1
                    continue
                expected = checksum(
                    row["ts_utc"],
                    int(row["iso_week"]),
                    int(row["weekday"]),
                    int(row["day_of_year"]),
                )
                if row.get("checksum") == expected:
                    ok += 1
                else:
                    bad += 1
                    bad_rows.append(
                        (csv_path.name, row.get("ts_utc"), row.get("checksum"), expected)
                    )

    print(f"[update.py] verify: {total} rows, {ok} ok, {bad} mismatched, {legacy} legacy (v1)")
    for name, ts, got, want in bad_rows[:10]:
        print(f"  MISMATCH {name} {ts}: stored={got} expected={want}")
    if bad:
        print(f"[update.py] verify: FAILED ({bad} mismatched rows)")
        return 1
    print("[update.py] verify: OK")
    return 0


def main(argv: Optional[list] = None) -> int:
    epilog = (__doc__ or "").split("CLI::", 1)[1].strip() if __doc__ and "CLI::" in __doc__ else ""
    parser = argparse.ArgumentParser(
        description="Append one row to the hourly CSV time ledger.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    parser.add_argument("--dry-run", action="store_true", help="print the row without writing")
    parser.add_argument("--force", action="store_true", help="append even if the hour exists")
    parser.add_argument("--verify", action="store_true", help="revalidate ledger checksums")
    args = parser.parse_args(argv)

    if args.verify:
        return verify_ledger(DATA)
    return append_row(DATA, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
