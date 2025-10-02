#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

def kyiv_tz():
    now = datetime.now(timezone.utc)
    offset = 3 if 3 <= now.month <= 10 else 2  # емуляція EET/EEST без зовн. API
    return timezone(timedelta(hours=offset), name=f"UTC+{offset}")

def ny_tz():
    now = datetime.now(timezone.utc)
    offset = -4 if 3 <= now.month <= 11 else -5  # умовний EDT/EST
    return timezone(timedelta(hours=offset), name=f"UTC{offset}")

def build_row():
    now_utc = datetime.now(timezone.utc)
    kyiv = now_utc.astimezone(kyiv_tz())
    ny   = now_utc.astimezone(ny_tz())

    iso_week   = int(now_utc.strftime("%V"))
    weekday    = int(now_utc.strftime("%u"))   # 1..7
    day_of_yr  = int(now_utc.strftime("%j"))
    month      = now_utc.month
    quarter    = (month - 1) // 3 + 1
    is_month_start   = 1 if now_utc.day == 1 else 0
    is_quarter_start = 1 if (month in (1,4,7,10) and now_utc.day == 1) else 0

    raw = f"{now_utc.isoformat()}|{iso_week}|{weekday}|{day_of_yr}"
    checksum = hashlib.sha256(raw.encode()).hexdigest()[:12]

    return {
        "ts_utc": now_utc.isoformat(timespec="seconds"),
        "unix":   int(now_utc.timestamp()),
        "iso_week": iso_week,
        "weekday":  weekday,
        "hour_utc": now_utc.hour,
        "day_of_year": day_of_yr,
        "month": month,
        "quarter": quarter,
        "is_month_start": is_month_start,
        "is_quarter_start": is_quarter_start,
        "kyiv": kyiv.isoformat(timespec="seconds"),
        "new_york": ny.isoformat(timespec="seconds"),
        "checksum": checksum,
        "format": "csv-ledger-v1"
    }

def main() -> int:
    now_utc = datetime.now(timezone.utc)
    day_dir = DATA / now_utc.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    outfile = day_dir / "hourly.csv"

    headers = [
        "ts_utc","unix","iso_week","weekday","hour_utc","day_of_year",
        "month","quarter","is_month_start","is_quarter_start",
        "kyiv","new_york","checksum","format"
    ]

    file_exists = outfile.exists()
    with outfile.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
        writer.writerow(build_row())

    print(f"[update.py] appended row -> {outfile.relative_to(ROOT)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
