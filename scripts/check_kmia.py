import json
import os
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

STATION = "KMIA"
THRESHOLD_IN = 0.10
NWS_URL = "https://api.weather.gov/stations/KMIA/observations/latest"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
DATA = Path("docs/data.json")

def get_nws():
    req = urllib.request.Request(
        NWS_URL,
        headers={
            "User-Agent": "RainWatch-KMIA/1.0",
            "Accept": "application/geo+json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)

def inches_from_mm(value):
    if value is None:
        return None
    return float(value) / 25.4

def send_ntfy(rain, observed_at):
    if not NTFY_TOPIC:
        raise RuntimeError("NTFY_TOPIC GitHub secret is not configured.")

    url = "https://ntfy.sh/" + NTFY_TOPIC
    body = (
        f"KMIA recorded {rain:.2f} inches of precipitation in the last hour. "
        f"Threshold: {THRESHOLD_IN:.2f} in/hr. Observation: {observed_at}"
    ).encode()

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Title": "🌧️ RainWatch: Rain threshold reached",
            "Priority": "high",
            "Tags": "rain,warning",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        response.read()

def main():
    payload = get_nws()
    props = payload["properties"]

    observed_at = props.get("timestamp")
    rain = inches_from_mm(
        (props.get("precipitationLastHour") or {}).get("value")
    )

    previous = {}
    if DATA.exists():
        try:
            previous = json.loads(DATA.read_text())
        except Exception:
            previous = {}

    alerted = False

    # One notification per unique NOAA observation that meets the threshold.
    if (
        rain is not None
        and rain >= THRESHOLD_IN
        and observed_at
        and previous.get("last_alert_observation") != observed_at
    ):
        send_ntfy(rain, observed_at)
        alerted = True

    output = {
        "station": STATION,
        "threshold_in_hr": THRESHOLD_IN,
        "rain_1hr_in": rain,
        "observed_at": observed_at,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "https://forecast.weather.gov/data/obhistory/KMIA.html",
        "api_source": NWS_URL,
        "alerted": alerted,
        "last_alert_observation": observed_at if alerted else previous.get("last_alert_observation"),
    }

    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(output, indent=2) + "\n")

    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
