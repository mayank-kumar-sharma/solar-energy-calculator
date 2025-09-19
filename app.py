# app.py
import streamlit as st
import requests
import json
from shapely.geometry import shape
from shapely.ops import transform
import pyproj
from functools import partial

# -----------------------------
# Config / Constants
# -----------------------------
PVGIS_API = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"

STATE_TARIFFS = {
    "Rajasthan": 6.0,
    "Delhi": 8.0,
    "Maharashtra": 9.0,
    "Uttar Pradesh": 7.0,
    "Gujarat": 7.5,
    "Tamil Nadu": 6.5,
    "Karnataka": 7.2,
    "Default": 7.0
}

PANEL_EFFICIENCY = 0.20
SYSTEM_DERATE = 0.85
COST_PER_KW = 50000  # INR
CO2_FACTOR = 0.82   # kg CO₂ / kWh

# -----------------------------
# Helper functions
# -----------------------------
def geocode_address(address):
    """Get lat/lon from address using Nominatim."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    r = requests.get(url, params=params)
    if r.status_code == 200 and r.json():
        data = r.json()[0]
        return float(data["lat"]), float(data["lon"]), data.get("display_name", "")
    return None, None, None

def get_building_polygon(lat, lon):
    """Query OSM Overpass for building polygons near given coordinates."""
    overpass_url = "http://overpass-api.de/api/interpreter"
    query = f"""
    [out:json];
    way(around:30,{lat},{lon})["building"];
    out geom;
    """
    r = requests.get(overpass_url, params={"data": query})
    if r.status_code != 200:
        return None

    data = r.json()
    if not data["elements"]:
        return None

    coords = [(pt["lon"], pt["lat"]) for pt in data["elements"][0]["geometry"]]
    poly = {"type": "Polygon", "coordinates": [coords]}
    return compute_area(poly)

def compute_area(geojson_polygon):
    """Compute polygon area in square meters."""
    geom = shape(geojson_polygon)
    proj = partial(
        pyproj.transform,
        pyproj.Proj(init='epsg:4326'),
        pyproj.Proj(proj='aea', lat1=geom.bounds[1], lat2=geom.bounds[3])
    )
    return transform(proj, geom).area

def get_pvgis_irradiance(lat, lon):
    """Fetch annual irradiance (GHI) from PVGIS in kWh/m²/year."""
    params = {
        "lat": lat,
        "lon": lon,
        "outputformat": "json",
        "browser": 1,
        "usehorizon": 1,
    }
    r = requests.get(PVGIS_API, params=params)
    if r.status_code != 200:
        return None
    try:
        data = r.json()
        return data["outputs"]["totals"]["fixed"]["E_y"]
    except Exception:
        return None

def calculate_results(area, shadow_area, irradiance, orientation_factor, tariff):
    """Perform solar calculations."""
    effective_area = max(area - shadow_area, 0)

    capacity_kw = effective_area / 10
    annual_gen = effective_area * irradiance * PANEL_EFFICIENCY * SYSTEM_DERATE * orientation_factor
    annual_savings = annual_gen * tariff
    inst_cost = capacity_kw * COST_PER_KW
    payback_years = inst_cost / annual_savings if annual_savings > 0 else None
    co2_tons = (annual_gen * CO2_FACTOR) / 1000

    return {
        "effective_area": effective_area,
        "capacity_kw": capacity_kw,
        "annual_gen": annual_gen,
        "annual_savings": annual_savings,
        "payback_years": payback_years,
        "co2_tons": co2_tons,
        "inst_cost": inst_cost,
    }

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("☀️ Solar Rooftop Estimation Tool")
st.markdown("Estimate rooftop solar capacity, energy generation, savings, and CO₂ benefits.")

# Roof area method
area_method = st.radio("Select roof area input method:", ["Enter directly", "Get from address"])

roof_area = None
lat = lon = None
location_name = ""

# Always ask for address (for irradiance)
address = st.text_input("Enter address (required for irradiance):")
if address:
    lat, lon, location_name = geocode_address(address)
    if lat and lon:
        st.success(f"Geocoded: {location_name} ({lat:.4f}, {lon:.4f})")

        if area_method == "Get from address":
            poly_area = get_building_polygon(lat, lon)
            if poly_area:
                roof_area = poly_area
                st.info(f"Detected building area: {roof_area:.2f} m²")
            else:
                roof_area = 100.0
                st.warning("No footprint found. Using default 100 m².")
    else:
        st.error("Could not geocode address.")

if area_method == "Enter directly":
    roof_area = st.number_input("Enter roof area (m²):", min_value=10.0, step=10.0)

# Other inputs
shadow_area = st.number_input("Enter shadow-covered area (m², optional):", min_value=0.0, value=0.0)
orientation = st.selectbox("Orientation of panels:", ["South (best)", "East", "West", "North"])
orientation_factor = {"South (best)": 1.0, "East": 0.8, "West": 0.8, "North": 0.5}[orientation]
state = st.selectbox("Select state:", list(STATE_TARIFFS.keys()))
tariff = st.number_input("Electricity tariff (₹/kWh):", value=STATE_TARIFFS.get(state, 7.0))

# Button to calculate
if st.button("🔍 Calculate Results"):
    if roof_area and lat and lon:
        irradiance = get_pvgis_irradiance(lat, lon)
        if not irradiance:
            st.error("Could not fetch irradiance from PVGIS.")
        else:
            results = calculate_results(roof_area, shadow_area, irradiance, orientation_factor, tariff)
            st.subheader("📊 Results")
            st.write(f"**Effective Area:** {results['effective_area']:.2f} m²")
            st.write(f"**Solar Capacity:** {results['capacity_kw']:.2f} kW")
            st.write(f"**Annual Generation:** {results['annual_gen']:.2f} kWh")
            st.write(f"**Annual Savings:** ₹{results['annual_savings']:.2f}")
            st.write(f"**Installation Cost:** ₹{results['inst_cost']:.2f}")
            st.write(f"**Payback Period:** {results['payback_years']:.2f} years")
            st.write(f"**CO₂ Saved:** {results['co2_tons']:.2f} tons/year")
    else:
        st.warning("Please provide both roof area and address.")
