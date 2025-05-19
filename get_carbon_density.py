import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta

def get_current_carbon_intensity(username, password, latitude, longitude):
    # Step 1: Login to get token
    login_url = 'https://api.watttime.org/login'
    rsp = requests.get(login_url, auth=HTTPBasicAuth(username, password))
    rsp.raise_for_status()
    TOKEN = rsp.json()['token']
    
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    # Step 2: Get region from lat/lon
    region_url = "https://api.watttime.org/v3/region-from-loc"
    region_params = {"latitude": str(latitude), "longitude": str(longitude), "signal_type": "co2_moer"}
    region_rsp = requests.get(region_url, headers=headers, params=region_params)
    region_rsp.raise_for_status()
    region = region_rsp.json()['region']

    # Step 3: Try to get recent carbon intensity (past 10 minutes)
    now = datetime.utcnow()
    start_time = (now - timedelta(minutes=10)).replace(second=0, microsecond=0).isoformat() + "+00:00"
    end_time = now.replace(second=0, microsecond=0).isoformat() + "+00:00"

    hist_url = "https://api.watttime.org/v3/historical"
    hist_params = {
        "region": region,
        "start": start_time,
        "end": end_time,
        "signal_type": "co2_moer",
    }
    hist_rsp = requests.get(hist_url, headers=headers, params=hist_params)
    hist_rsp.raise_for_status()
    data = hist_rsp.json().get("data", [])

    if not data:
        raise Exception("No carbon intensity data returned in the last 10 minutes.")

    latest_point = data[-1]
    return {
        "region": region,
        "point_time": latest_point["point_time"],
        "value": latest_point["value"],
        "units": hist_rsp.json()["meta"]["units"]
    }

def compute_carbon_emission(energy_joules, intensity_lbs_per_mwh):
    lbs_per_joule = intensity_lbs_per_mwh / 3.6e9
    total_lbs = energy_joules * lbs_per_joule
    total_kg = total_lbs * 0.453592
    return total_lbs, total_kg


