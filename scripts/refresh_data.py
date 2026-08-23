#!/usr/bin/env python3
"""Refresh kiosk data files: shared iCloud calendar + Google Photos album.

Run by .github/workflows/refresh-data.yml on a schedule; also runnable
locally:  pip install requests icalendar recurring-ical-events
          python3 scripts/refresh_data.py

Writes data/calendar.json (events expanded from RRULEs, window of
-7..+62 days) and data/photos.json (image URLs scraped from the shared
album page). Output is deterministic for unchanged sources so the
workflow only commits real changes.
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from icalendar import Calendar
import recurring_ical_events

CAL_URL = (
    "https://p34-caldav.icloud.com/published/2/"
    "MTM1MTEyOTU3OTEzNTExMs-neKrOI1aIY3Ocy4L62AHEfk_MeKXXMW5i7roKyAIuZ5CO"
    "PzYojmSBROX3Cz_nWKRkN7DCeyVfo6d8qY1C6_w"
)
ALBUM_URL = "https://photos.app.goo.gl/jRNmYkw8CJkbVbVb6"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}
MAX_PHOTOS = 60
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def refresh_calendar() -> None:
    ics = requests.get(CAL_URL, timeout=60).content
    cal = Calendar.from_ical(ics)
    name = str(cal.get("X-WR-CALNAME", "CALENDAR"))
    start = date.today() - timedelta(days=7)
    end = date.today() + timedelta(days=62)
    events = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        dtstart = ev["DTSTART"].dt
        dtend = ev["DTEND"].dt if "DTEND" in ev else dtstart
        all_day = not isinstance(dtstart, datetime)
        if all_day and dtend <= dtstart:
            # DTEND is exclusive; guarantee at least a one-day span
            dtend = dtstart + timedelta(days=1)
        events.append(
            {
                "t": str(ev.get("SUMMARY", "")).strip(),
                "s": dtstart.isoformat(),
                "e": dtend.isoformat(),
                "d": all_day,
                "loc": str(ev.get("LOCATION", "")).strip(),
            }
        )
    events.sort(key=lambda e: (e["s"], e["t"]))
    write_json(DATA_DIR / "calendar.json", {"calendar": name, "events": events})
    print(f"calendar.json: {len(events)} events from '{name}'")


def refresh_photos() -> None:
    html = requests.get(ALBUM_URL, headers=UA, timeout=60).text
    items = re.findall(
        r'\["(https://lh3\.googleusercontent\.com/pw/[^",]+)",(\d+),(\d+)', html
    )
    seen, photos = set(), []
    for url, w, h in items:
        if url in seen:
            continue
        seen.add(url)
        photos.append({"u": url, "w": int(w), "h": int(h)})
        if len(photos) >= MAX_PHOTOS:
            break
    if not photos:
        raise RuntimeError("no photos parsed from album page (format change?)")
    write_json(DATA_DIR / "photos.json", {"photos": photos})
    print(f"photos.json: {len(photos)} photos")


def main() -> int:
    failures = 0
    for task in (refresh_calendar, refresh_photos):
        try:
            task()
        except Exception as exc:  # keep one source's failure from killing the other
            failures += 1
            print(f"ERROR in {task.__name__}: {exc}", file=sys.stderr)
    return 1 if failures == 2 else 0


if __name__ == "__main__":
    sys.exit(main())
