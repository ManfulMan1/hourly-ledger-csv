"""Tests for scripts/update.py — stdlib-only (unittest)."""
import csv
import hashlib
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update", REPO_ROOT / "scripts" / "update.py")
assert SPEC is not None and SPEC.loader is not None
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)

UTC = timezone.utc


def utc(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=UTC)


class TestBuildRow(unittest.TestCase):
    def test_basic_fields(self):
        row = update.build_row(utc(2026, 8, 12, 14, 30, 5))
        self.assertEqual(row["ts_utc"], "2026-08-12T14:30:05+00:00")
        self.assertEqual(row["unix"], int(utc(2026, 8, 12, 14, 30, 5).timestamp()))
        self.assertEqual(row["iso_week"], 33)
        self.assertEqual(row["weekday"], 3)  # Wednesday
        self.assertEqual(row["hour_utc"], 14)
        self.assertEqual(row["day_of_year"], 224)
        self.assertEqual(row["month"], 8)
        self.assertEqual(row["quarter"], 3)
        self.assertEqual(row["is_month_start"], 0)
        self.assertEqual(row["is_quarter_start"], 0)
        self.assertEqual(row["format"], update.FORMAT)

    def test_month_and_quarter_starts(self):
        row = update.build_row(utc(2026, 10, 1, 0, 0, 0))
        self.assertEqual(row["is_month_start"], 1)
        self.assertEqual(row["is_quarter_start"], 1)
        row = update.build_row(utc(2026, 4, 1))
        self.assertEqual(row["is_quarter_start"], 1)
        row = update.build_row(utc(2026, 6, 1))
        self.assertEqual(row["is_quarter_start"], 0)

    def test_iso_week_monday(self):
        # 2026-01-01 is a Thursday -> ISO week 1; Monday of week 1 is 2025-12-29
        row = update.build_row(utc(2026, 1, 1))
        self.assertEqual(row["iso_week"], 1)
        self.assertEqual(row["weekday"], 4)
        row = update.build_row(utc(2025, 12, 29))
        self.assertEqual(row["iso_week"], 1)
        self.assertEqual(row["weekday"], 1)

    def test_checksum_reproducible_from_row(self):
        row = update.build_row(utc(2026, 8, 12, 14, 30, 5))
        raw = f"{row['ts_utc']}|{row['iso_week']}|{row['weekday']}|{row['day_of_year']}"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:12]
        self.assertEqual(row["checksum"], expected)
        # And the helper agrees with the row values exactly as stored.
        self.assertEqual(
            update.checksum(row["ts_utc"], row["iso_week"], row["weekday"], row["day_of_year"]),
            row["checksum"],
        )

    def test_microseconds_do_not_leak_into_checksum(self):
        # v1 bug: isoformat() included microseconds that were not stored,
        # making the checksum unreproducible. ts_utc must be seconds-precision.
        row = update.build_row(utc(2026, 8, 12, 14, 30, 5))
        self.assertNotIn(".", row["ts_utc"].split("+")[0])
        self.assertEqual(len(row["ts_utc"]), 25)  # YYYY-MM-DDTHH:MM:SS+00:00


class TestTimezones(unittest.TestCase):
    def test_kyiv_after_dst_abolition(self):
        # Ukraine stopped seasonal clock changes in July 2024 -> UTC+2 year-round.
        for dt in [
            utc(2026, 1, 15, 12),
            utc(2026, 8, 12, 12),   # old code wrongly said +03:00 here
            utc(2026, 7, 1, 12),
        ]:
            k = update.kyiv_local(dt)
            self.assertEqual(k.utcoffset(), timedelta(hours=2), f"Kyiv offset wrong for {dt}")

    def test_kyiv_summer_2024_still_dst(self):
        # 2024-03-31 (last DST switch): Kyiv is UTC+3 that day.
        k = update.kyiv_local(utc(2024, 3, 31, 12))
        self.assertEqual(k.utcoffset(), timedelta(hours=3))

    def test_ny_dst_boundaries(self):
        # 2026: DST starts Mar 8 07:00 UTC, ends Nov 1 06:00 UTC
        # (second Sun Mar / first Sun Nov, 2am local).
        self.assertEqual(update.ny_local(utc(2026, 3, 7, 12)).utcoffset(), timedelta(hours=-5))
        self.assertEqual(update.ny_local(utc(2026, 3, 8, 6)).utcoffset(), timedelta(hours=-5))
        self.assertEqual(update.ny_local(utc(2026, 3, 8, 7)).utcoffset(), timedelta(hours=-4))
        self.assertEqual(update.ny_local(utc(2026, 3, 8, 12)).utcoffset(), timedelta(hours=-4))
        self.assertEqual(update.ny_local(utc(2026, 11, 1, 5)).utcoffset(), timedelta(hours=-4))
        self.assertEqual(update.ny_local(utc(2026, 11, 1, 6)).utcoffset(), timedelta(hours=-5))
        self.assertEqual(update.ny_local(utc(2026, 11, 2, 12)).utcoffset(), timedelta(hours=-5))

    def test_ny_winter(self):
        self.assertEqual(update.ny_local(utc(2026, 1, 15, 12)).utcoffset(), timedelta(hours=-5))


class TestAppend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_creates_file_with_header(self):
        rc = update.append_row(self.data, now_utc=utc(2026, 8, 12, 14))
        self.assertEqual(rc, 0)
        outfile = self.data / "2026-08-12" / "hourly.csv"
        self.assertTrue(outfile.exists())
        with outfile.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hour_utc"], "14")
        self.assertEqual(rows[0]["format"], update.FORMAT)

    def test_duplicate_hour_skipped_unless_force(self):
        update.append_row(self.data, now_utc=utc(2026, 8, 12, 14))
        rc = update.append_row(self.data, now_utc=utc(2026, 8, 12, 14, 30))
        self.assertEqual(rc, 0)  # skipped (no-op)
        with (self.data / "2026-08-12" / "hourly.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)  # nothing appended
        rc = update.append_row(self.data, now_utc=utc(2026, 8, 12, 14, 45), force=True)
        self.assertEqual(rc, 0)
        with (self.data / "2026-08-12" / "hourly.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)

    def test_different_hour_appends(self):
        update.append_row(self.data, now_utc=utc(2026, 8, 12, 14))
        rc = update.append_row(self.data, now_utc=utc(2026, 8, 12, 15))
        self.assertEqual(rc, 0)
        with (self.data / "2026-08-12" / "hourly.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["hour_utc"] for r in rows], ["14", "15"])

    def test_dry_run_writes_nothing(self):
        rc = update.append_row(self.data, now_utc=utc(2026, 8, 12, 14), dry_run=True)
        self.assertEqual(rc, 0)
        self.assertFalse((self.data / "2026-08-12").exists())


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_verify_ok_on_clean_ledger(self):
        update.append_row(self.data, now_utc=utc(2026, 8, 12, 14))
        update.append_row(self.data, now_utc=utc(2026, 8, 13, 9))
        self.assertEqual(update.verify_ledger(self.data), 0)

    def test_verify_detects_tampered_checksum(self):
        update.append_row(self.data, now_utc=utc(2026, 8, 12, 14))
        outfile = self.data / "2026-08-12" / "hourly.csv"
        with outfile.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        rows[0]["checksum"] = "deadbeefcafe"
        with outfile.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=update.HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        self.assertEqual(update.verify_ledger(self.data), 1)

    def test_verify_counts_legacy_rows_without_failing(self):
        # A v1 row (old checksum scheme) should count as legacy, not mismatch.
        update.append_row(self.data, now_utc=utc(2026, 8, 12, 14))
        outfile = self.data / "2026-08-12" / "hourly.csv"
        with outfile.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        rows[0]["format"] = "csv-ledger-v1"
        rows[0]["checksum"] = "oldstyle"
        with outfile.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=update.HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        self.assertEqual(update.verify_ledger(self.data), 0)


if __name__ == "__main__":
    unittest.main()
