import urllib.request
from datetime import datetime, timedelta
from contextlib import closing


def fetch_hydrometric_csv(province):
    base_url = "https://dd.weather.gc.ca/{date}/WXO-DD/hydrometric/csv/{province}/hourly/"

    for delta in [0, 1]:  # try today, then yesterday
        date_str = (datetime.utcnow() - timedelta(days=delta)).strftime("%Y%m%d")
        url = base_url.format(date=date_str, province=province)
        try:
            with closing( urllib.request.urlopen(url, timeout=30)) as response:
                data = response.read()
            print(f"Success: {url}")
            return data
        except Exception as e:
            print(f"Failed ({date_str}): {e}")

    raise RuntimeError(f"Could not retrieve data for province '{province}' for today or yesterday.")


if __name__ == "__main__":
    data = fetch_hydrometric_csv("ON")
