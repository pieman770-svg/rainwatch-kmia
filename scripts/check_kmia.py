import json
import os
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import urllib.request


STATION = "KMIA"
THRESHOLD_IN = 0.10
NWS_HISTORY_URL = "https://forecast.weather.gov/data/obhistory/KMIA.html"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
DATA = Path("docs/data.json")


class TableParser(HTMLParser):
    """Extract rows from the NWS observation-history table."""

    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False

        self.current_cell = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag == "table":
            self.in_table = True

        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []

        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in ("td", "th") and self.in_cell:
            value = " ".join("".join(self.current_cell).split())
            self.current_row.append(value)
            self.current_cell = []
            self.in_cell = False

        elif tag == "tr" and self.in_row:
            if self.current_row:
                self.rows.append(self.current_row)

            self.current_row = []
            self.in_row = False

        elif tag == "table":
            self.in_table = False


def now_utc():
    return datetime.now(timezone.utc)


def load_previous():
    if not DATA.exists():
        return {}

    try:
        return json.loads(DATA.read_text())
    except Exception:
        return {}


def save_data(data):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(data, indent=2) + "\n")


def fetch_history():
    request = urllib.request.Request(
        NWS_HISTORY_URL,
        headers={
            "User-Agent": "RainWatch-KMIA/1.0",
        },
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")

    return html


def find_observation_rows(html):
    parser = TableParser()
    parser.feed(html)

    # The NWS page has multiple tables. Find the table containing
    # the KMIA observation-history header.
    candidates = []

    for row in parser.rows:
        normalized = [cell.lower() for cell in row]

        if (
            "date" in normalized
            and any("time" in cell for cell in normalized)
        ):
            candidates.append(row)

    # Locate the table rows using the known NWS structure.
    #
    # We identify data rows by their first two fields:
    #   Date = day number
    #   Time = HH:MM
    #
    # The precipitation 1-hour column is the final group of
    # columns on the NWS table:
    #
    #   ... altimeter | sea level | 1 hr | 3 hr | 6 hr
    #
    data_rows = []

    for row in parser.rows:
        if len(row) < 17:
            continue

        date_value = row[0].strip()
        time_value = row[1].strip()

        if not date_value.isdigit():
            continue

        if ":" not in time_value:
            continue

        data_rows.append(row)

    return data_rows


def parse_precipitation(row):
    """
    NWS KMIA table layout currently places:
        1 hr = column 15
        3 hr = column 16
        6 hr = column 17

    We only use the 1-hour value.
    """

    if len(row) <= 15:
        return None

    value = row[15].strip()

    if not value:
        return None

    try:
        return float(value)
    except ValueError:
        return None


def parse_observation(row):
    date_value = row[0].strip()
    time_value = row[1].strip()

    # NWS displays the day number but not the month/year in each row.
    # The page itself represents the current three-day observation
    # history. We use the current month/year and adjust across a
    # month boundary when necessary.

    now = datetime.now()

    day = int(date_value)
    hour, minute = [int(x) for x in time_value.split(":")]

    year = now.year
    month = now.month

    # If the displayed day is ahead of today's day, it belongs to
    # the previous month.
    if day > now.day:
        if month == 1:
            month = 12
            year -= 1
        else:
            month -= 1

    return datetime(
        year,
        month,
        day,
        hour,
        minute,
    )


def send_ntfy(rain, observed_at):
    if not NTFY_TOPIC:
        raise RuntimeError(
            "NTFY_TOPIC GitHub secret is not configured."
        )

    url = "https://ntfy.sh/" + NTFY_TOPIC

    body = (
        f"KMIA recorded {rain:.2f} inches of precipitation "
        f"in the previous 1-hour observation.\n\n"
        f"Threshold: {THRESHOLD_IN:.2f} in/hr\n"
        f"Observation: {observed_at}"
    ).encode()

    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Title": "🌧️ RainWatch: Rain threshold reached",
            "Priority": "high",
            "Tags": "rain,warning",
        },
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def main():
    checked_at = now_utc().isoformat()
    previous = load_previous()

    # ---------------------------------------------------------
    # 1. Fetch NWS observation history
    # ---------------------------------------------------------

    try:
        html = fetch_history()

    except Exception as exc:
        output = {
            **previous,
            "station": STATION,
            "threshold_in_hr": THRESHOLD_IN,
            "status": "error",
            "error": f"NWS history request failed: {exc}",
            "fetched_at": checked_at,
            "source": NWS_HISTORY_URL,
        }

        save_data(output)

        print(json.dumps(output, indent=2))

        raise


    # ---------------------------------------------------------
    # 2. Parse observation rows
    # ---------------------------------------------------------

    rows = find_observation_rows(html)

    if not rows:
        output = {
            **previous,
            "station": STATION,
            "threshold_in_hr": THRESHOLD_IN,
            "status": "error",
            "error": "Could not find KMIA observation rows.",
            "fetched_at": checked_at,
            "source": NWS_HISTORY_URL,
        }

        save_data(output)

        print(json.dumps(output, indent=2))

        raise RuntimeError(
            "Could not find KMIA observation rows."
        )


    # The NWS page is newest-first, so the first data row is
    # the newest observation.
    row = rows[0]

    observed_at = parse_observation(row)
    rain = parse_precipitation(row)

    observation_id = observed_at.isoformat()


    # ---------------------------------------------------------
    # 3. Handle blank 1-hour precipitation
    # ---------------------------------------------------------

    if rain is None:
        output = {
            "station": STATION,
            "threshold_in_hr": THRESHOLD_IN,
            "status": "no_data",
            "error": None,
            "rain_1hr_in": None,
            "observed_at": observation_id,
            "fetched_at": checked_at,
            "source": NWS_HISTORY_URL,
            "alerted": False,
            "last_alert_observation": previous.get(
                "last_alert_observation"
            ),
        }

        save_data(output)

        print(json.dumps(output, indent=2))

        return


    # ---------------------------------------------------------
    # 4. Determine whether alert is required
    # ---------------------------------------------------------

    already_alerted = (
        previous.get("last_alert_observation")
        == observation_id
    )

    should_alert = (
        rain >= THRESHOLD_IN
        and not already_alerted
    )

    alerted = False

    if should_alert:
        send_ntfy(rain, observation_id)
        alerted = True


    # ---------------------------------------------------------
    # 5. Save successful observation
    # ---------------------------------------------------------

    output = {
        "station": STATION,
        "threshold_in_hr": THRESHOLD_IN,
        "status": "online",
        "error": None,
        "rain_1hr_in": round(rain, 4),
        "observed_at": observation_id,
        "fetched_at": checked_at,
        "source": NWS_HISTORY_URL,
        "alerted": alerted,
        "last_alert_observation": (
            observation_id
            if alerted
            else previous.get("last_alert_observation")
        ),
    }

    save_data(output)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
