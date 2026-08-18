import json
import os
from datetime import datetime, timezone

from pathlib import Path
import urllib.error
import urllib.request


STATION = "KMIA"
THRESHOLD_IN = 0.10
NWS_URL = "https://api.weather.gov/stations/KMIA/observations/latest"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
DATA = Path("docs/data.json")

# Consider an observation stale after this many minutes.
MAX_OBSERVATION_AGE_MINUTES = 90


def now_utc():
    return datetime.now(timezone.utc)


def get_nws():
    req = urllib.request.Request(
        NWS_URL,
        headers={
            "User-Agent": "RainWatch-KMIA/1.1",
            "Accept": "application/geo+json",
        },
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def inches_from_mm(value):
    if value is None:
        return None

    return float(value) / 25.4


def load_previous():
    if not DATA.exists():
        return {}

    try:
        return json.loads(DATA.read_text())
    except Exception:
        return {}


def save_data(output):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(output, indent=2) + "\n")


def send_ntfy(rain, observed_at):
    if not NTFY_TOPIC:
        raise RuntimeError("NTFY_TOPIC GitHub secret is not configured.")

    url = "https://ntfy.sh/" + NTFY_TOPIC

    body = (
        f"KMIA recorded {rain:.2f} inches of precipitation "
        f"in the last hour.\n\n"
        f"Threshold: {THRESHOLD_IN:.2f} in/hr\n"
        f"Observation: {observed_at}"
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


def parse_observation_time(observed_at):
    if not observed_at:
        return None

    try:
        return datetime.fromisoformat(
            observed_at.replace("Z", "+00:00")
        )
    except ValueError:
        return None


def main():
    checked_at = now_utc().isoformat()
    previous = load_previous()

    # ---------------------------------------------------------
    # 1. Fetch NWS data
    # ---------------------------------------------------------

    try:
        payload = get_nws()

    except Exception as exc:
        output = {
            **previous,
            "station": STATION,
            "threshold_in_hr": THRESHOLD_IN,
            "status": "error",
            "error": f"NWS request failed: {exc}",
            "fetched_at": checked_at,
            "source": "https://forecast.weather.gov/data/obhistory/KMIA.html",
            "api_source": NWS_URL,
        }

        save_data(output)

        print(json.dumps(output, indent=2))

        # Fail the GitHub Action so the problem is visible.
        raise


    # ---------------------------------------------------------
    # 2. Extract observation
    # ---------------------------------------------------------

    try:
        props = payload["properties"]

    except (KeyError, TypeError) as exc:
        output = {
            **previous,
            "station": STATION,
            "threshold_in_hr": THRESHOLD_IN,
            "status": "error",
            "error": f"Unexpected NWS response: {exc}",
            "fetched_at": checked_at,
            "source": "https://forecast.weather.gov/data/obhistory/KMIA.html",
            "api_source": NWS_URL,
        }

        save_data(output)

        print(json.dumps(output, indent=2))

        raise


    observed_at = props.get("timestamp")

    precipitation = props.get("precipitationLastHour")

    rain_mm = None

    if isinstance(precipitation, dict):
        rain_mm = precipitation.get("value")

    rain = inches_from_mm(rain_mm)


    # ---------------------------------------------------------
    # 3. Check observation age
    # ---------------------------------------------------------

    observation_time = parse_observation_time(observed_at)

    observation_age_minutes = None
    stale = False

    if observation_time:
        observation_age_minutes = (
            now_utc() - observation_time
        ).total_seconds() / 60

        stale = observation_age_minutes > MAX_OBSERVATION_AGE_MINUTES


    # ---------------------------------------------------------
    # 4. Handle missing precipitation data
    # ---------------------------------------------------------

    if rain is None:
        output = {
            **previous,
            "station": STATION,
            "threshold_in_hr": THRESHOLD_IN,
            "status": "no_data",
            "error": None,
            "rain_1hr_in": None,
            "observed_at": observed_at,
            "observation_age_minutes": observation_age_minutes,
            "stale_observation": stale,
            "fetched_at": checked_at,
            "source": "https://forecast.weather.gov/data/obhistory/KMIA.html",
            "api_source": NWS_URL,
            "alerted": False,
            "last_alert_observation": previous.get(
                "last_alert_observation"
            ),
        }

        save_data(output)

        print(json.dumps(output, indent=2))

        return


    # ---------------------------------------------------------
    # 5. Handle stale observations
    # ---------------------------------------------------------

    if stale:
        output = {
            **previous,
            "station": STATION,
            "threshold_in_hr": THRESHOLD_IN,
            "status": "stale",
            "error": (
                f"NWS observation is "
                f"{observation_age_minutes:.0f} minutes old."
            ),
            "rain_1hr_in": rain,
            "observed_at": observed_at,
            "observation_age_minutes": observation_age_minutes,
            "stale_observation": True,
            "fetched_at": checked_at,
            "source": "https://forecast.weather.gov/data/obhistory/KMIA.html",
            "api_source": NWS_URL,
            "alerted": False,
            "last_alert_observation": previous.get(
                "last_alert_observation"
            ),
        }

        save_data(output)

        print(json.dumps(output, indent=2))

        return


    # ---------------------------------------------------------
    # 6. Determine whether an alert is required
    # ---------------------------------------------------------

    alerted = False

    should_alert = (
        rain >= THRESHOLD_IN
        and observed_at
        and previous.get("last_alert_observation") != observed_at
    )


    if should_alert:
        send_ntfy(rain, observed_at)
        alerted = True


    # ---------------------------------------------------------
    # 7. Save healthy observation
    # ---------------------------------------------------------

    output = {
        "station": STATION,
        "threshold_in_hr": THRESHOLD_IN,
        "status": "online",
        "error": None,
        "rain_1hr_in": round(rain, 4),
        "observed_at": observed_at,
        "observation_age_minutes": (
            round(observation_age_minutes, 1)
            if observation_age_minutes is not None
            else None
        ),
        "stale_observation": False,
        "fetched_at": checked_at,
        "source": "https://forecast.weather.gov/data/obhistory/KMIA.html",
        "api_source": NWS_URL,
        "alerted": alerted,
        "last_alert_observation": (
            observed_at
            if alerted
            else previous.get("last_alert_observation")
        ),
    }

    save_data(output)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
