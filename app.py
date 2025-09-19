import streamlit as st
import requests
from shapely.geometry import shape
from shapely.ops import transform
from pyproj import CRS, Transformer

# -----------------------------
# Config / Constants
# -----------------------------
PVGIS_API = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"

STATE_IRRADIANCES = {
    "Andhra Pradesh": 1700, "Arunachal Pradesh": 1400, "Assam": 1500, "Bihar": 1600,
    "Chhattisgarh": 1800, "Goa": 1900, "Gujarat": 2000, "Haryana": 1700, "Himachal Pradesh": 1500,
    "Jharkhand": 1600, "Karnataka": 1800, "Kerala": 1600, "Madhya Pradesh": 1900, "Maharashtra": 1800,
    "Manipur": 1400, "Meghalaya": 1400, "Mizoram": 1400, "Nagaland": 1400, "Odisha": 1700,
    "Punjab": 1700, "Rajasthan": 2000, "Sikkim": 1400, "Tamil Nadu": 1900, "Telangana": 1800,
    "Tripura": 1500, "Uttar Pradesh": 1700, "Uttarakhand": 1500, "West Bengal": 1600,
    "Andaman and Nicobar Islands": 1700, "Chandigarh": 1700, 
    "Dadra and Nagar Haveli and Daman and Diu": 1800, "Lakshadweep": 1700, "Delhi": 1700
}

STATE_TARIFFS = {
    "Andhra Pradesh": 6.5, "Arunachal Pradesh": 6.0, "Assam": 6.0, "Bihar": 5.5,
    "Chhattisgarh": 5.5, "Goa": 6.5, "Gujarat": 7.5, "Haryana": 7.0, "Himachal Pradesh": 6.0,
    "Jharkhand": 5.5, "Karnataka": 7.2, "Kerala": 6.5, "Madhya Pradesh": 6.0, "Maharashtra": 9.0,
    "Manipur": 6.0, "Meghalaya": 6.0, "Mizoram": 6.0, "Nagaland": 6.0, "Odisha": 6.0,
    "Punjab": 6.5, "Rajasthan": 6.0, "Sikkim": 6.0, "Tamil Nadu": 6.5, "Telangana": 6.8,
    "Tripura": 6.0, "Uttar Pradesh": 7.0, "Uttarakhand": 6.0, "West Bengal": 6.5,
    "Andaman and Nicobar Islands": 6.5, "Chandigarh": 7.0, 
    "Dadra and Nagar Haveli and Daman and Diu": 7.0, "Lakshadweep": 6.5, "Delhi": 8.0
}

PANEL_EFFICIENCY = 0.20
SYSTEM_DERATE = 0.85
COST_PER_KW = 50000  # INR
CO2_FACTOR = 0.82    # kg CO₂ / kWh

HOUSE_TYPE_AREA = {
    "Villa": 250, "Independent House": 120, "2 BHK": 80, "3 BHK": 120, "Other": 100
}

# -----------------------------
# Helper functions
# -----------------------------
def geocode_address(address):
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address, "format": "json", "limit": 1}
        headers = {"User-Agent": "SolarApp/1.0 (your_email@example.com)"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200 and r.json():
            data = r.json()[0]
            return float(data["lat"]), float(data["lon"]), data.get("display_name", "")
    except Exception as e:
        st.warning(f"Geocoding failed: {e}")
    return None, None, None

def get_building_polygon(lat, lon):
    try:
        overpass_url = "http://overpass-api.de/api/interpreter"
        query = f"""
        [out:json];
        way(around:30,{lat},{lon})["building"];
        out geom;
        """
        r = requests.get(overpass_url, params={"data": query}, timeout=15)
        if r.status_code != 200 or not r.json().get("elements"):
            return None
        coords = [(pt["lon"], pt["lat"]) for pt in r.json()["elements"][0]["geometry"]]
        poly = {"type": "Polygon", "coordinates": [coords]}
        return compute_area(poly)
    except Exception as e:
        st.warning(f"OSM query failed: {e}")
        return None

def compute_area(geojson_polygon):
    geom = shape(geojson_polygon)
    transformer = Transformer.from_crs(CRS.from_epsg(4326),
                                       CRS.from_proj4("+proj=aea +lat_1={} +lat_2={} +lon_0={} +datum=WGS84"
                                                     .format(geom.bounds[1], geom.bounds[3],
                                                             (geom.bounds[0]+geom.bounds[2])/2)),
                                       always_xy=True)
    return transform(transformer.transform, geom).area

def get_pvgis_irradiance(lat, lon):
    """Fetch annual irradiance (GHI) from PVGIS. Returns value or None. Shows JSON in expander for debugging."""
    try:
        params = {"lat": lat, "lon": lon, "outputformat": "json", "browser": 1, "usehorizon": 1}
        r = requests.get(PVGIS_API, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            # Show full JSON for debugging
            with st.expander("🔹 PVGIS JSON Response (for debugging)"):
                st.json(data)
            totals = data.get("outputs", {}).get("totals", {}).get("fixed", {})
            # Try multiple keys
            irradiance = totals.get("E_y") or totals.get("E") or totals.get("GHI")
            return irradiance
        else:
            st.warning(f"PVGIS request returned status {r.status_code}")
    except Exception as e:
        st.warning(f"PVGIS fetch failed: {e}")
    return None

def calculate_results(area, shadow_area, irradiance, orientation_factor, tariff):
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
        "inst_cost": inst_cost
    }

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("☀️ Solar Rooftop Estimation Tool")
st.markdown("Estimate rooftop solar capacity, energy generation, savings, and CO₂ benefits.")

area_method = st.radio("Select roof area input method:", ["Enter directly", "Get from address"])
roof_area = None
lat = lon = None
location_name = ""

address = ""
if area_method == "Enter directly":
    roof_area = st.number_input("Enter roof area (m²):", min_value=10.0, step=10.0)
    address = st.text_input("Enter address (for irradiance):")
else:
    address = st.text_input("Enter address (roof + irradiance):")

if st.button("Use Demo Address"):
    address = "India Gate, Delhi"
    st.info(f"Demo address selected: {address}")

# -----------------------------
# Geocode + fallback logic
# -----------------------------
if address:
    lat, lon, location_name = geocode_address(address)
    if lat and lon:
        st.success(f"Geocoded: {location_name} ({lat:.4f}, {lon:.4f})")
        if area_method == "Get from address" and roof_area is None:
            poly_area = get_building_polygon(lat, lon)
            if poly_area:
                roof_area = poly_area
                st.info(f"Detected building area: {roof_area:.2f} m²")
    if roof_area is None:
        st.warning("Roof area could not be determined. Please select house type for default area.")
        house_type = st.selectbox("Select house type:", list(HOUSE_TYPE_AREA.keys()))
        roof_area = HOUSE_TYPE_AREA.get(house_type, 100)
        st.info(f"Using default roof area for {house_type}: {roof_area} m²")

# -----------------------------
# Shadow + orientation + tariff
# -----------------------------
st.markdown("**Shadow area:** Area covered by trees, walls, or other objects that reduce sunlight on panels.")
shadow_area = st.number_input("Enter shadow-covered area (m², optional):", min_value=0.0, value=0.0)
orientation = st.selectbox("Orientation of panels:", ["South (best)", "East", "West", "North"])
orientation_factor = {"South (best)": 1.0, "East": 0.8, "West": 0.8, "North": 0.5}[orientation]

state = st.selectbox("Select state/UT:", list(STATE_IRRADIANCES.keys()))
# PVGIS fetch
if lat and lon:
    irradiance = get_pvgis_irradiance(lat, lon)
    if not irradiance:
        irradiance = STATE_IRRADIANCES.get(state, 1700)
        st.warning(f"Could not fetch irradiance from PVGIS. Using state average: {irradiance} kWh/m²/yr")
else:
    irradiance = STATE_IRRADIANCES.get(state, 1700)

tariff = st.number_input("Electricity tariff (₹/kWh):", value=STATE_TARIFFS.get(state, 7.0))

# -----------------------------
# Calculate
# -----------------------------
if st.button("🔍 Calculate Solar Potential"):
    if roof_area:
        results = calculate_results(roof_area, shadow_area, irradiance, orientation_factor, tariff)
        with st.expander("📊 Results"):
            st.write(f"**Effective Area:** {results['effective_area']:.2f} m²")
            st.write(f"**Solar Capacity:** {results['capacity_kw']:.2f} kW")
            st.write(f"**Annual Generation:** {results['annual_gen']:.2f} kWh")
            st.write(f"**Annual Savings:** ₹{results['annual_savings']:.2f}")
            st.write(f"**Installation Cost:** ₹{results['inst_cost']:.2f}")
            st.write(f"**Payback Period:** {results['payback_years']:.2f} years")
            st.write(f"**CO₂ Saved:** {results['co2_tons']:.2f} tons/year")
    else:
        st.error("Please enter a valid roof area or select house type.")
