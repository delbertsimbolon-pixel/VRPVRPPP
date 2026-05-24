from solver import solve_cvrptw
import streamlit as st
import requests
import math
import pandas as pd
import folium
from folium.plugins import AntPath, TimestampedGeoJson
from streamlit_folium import st_folium

if "optimization_result" not in st.session_state:
    st.session_state.optimization_result = None

if "optimization_data" not in st.session_state:
    st.session_state.optimization_data = None

if "optimization_metrics" not in st.session_state:
    st.session_state.optimization_metrics = None


# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Gunadarma Exam Distribution DSS",
    layout="wide",
    page_icon="📦"
)


# --- HEADER ---
st.title("Examination Document Distribution Route Optimization System")
st.markdown("**Case Study:** Universitas Gunadarma CVRPTW Model")
st.markdown(
    "This decision-support system applies a Capacitated Vehicle Routing Problem with Time Windows "
    "model to optimize the distribution of examination papers and administrative documents from "
    "the duplication center to examination sites."
)


def get_osrm_matrices(data):
    """Fetch distance and travel-time matrices from OSRM."""
    coord_string = ";".join([f"{lon},{lat}" for lat, lon in data["raw_coords"]])
    url = f"http://router.project-osrm.org/table/v1/driving/{coord_string}?annotations=duration,distance"

    response = requests.get(url, timeout=20)
    response.raise_for_status()
    result = response.json()

    if result.get("code") != "Ok":
        raise ValueError(f"OSRM returned an invalid response: {result}")

    time_matrix = []
    for row in result["durations"]:
        time_matrix.append([
            math.ceil(value / 60) if value is not None else 999999
            for value in row
        ])

    distance_matrix = []
    for row in result["distances"]:
        distance_matrix.append([
            int(value) if value is not None else 999999999
            for value in row
        ])

    data["time_matrix"] = time_matrix
    data["distance_matrix"] = distance_matrix

    return data

def calculate_route_distance(route, distance_matrix):
    """Calculate total distance for a baseline/manual route."""
    total_distance = 0

    for i in range(len(route) - 1):
        from_node = route[i]
        to_node = route[i + 1]
        total_distance += distance_matrix[from_node][to_node]

    return total_distance

@st.cache_data(show_spinner=False)
def get_osrm_route_geometry(start_coord, end_coord):
    """
    Ambil geometri jalan asli dari OSRM untuk 1 segmen.
    start_coord dan end_coord formatnya: (lat, lon)
    """
    start_lat, start_lon = start_coord
    end_lat, end_lon = end_coord

    url = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
        f"?overview=full&geometries=geojson&steps=false"
    )

    response = requests.get(url, timeout=20)
    response.raise_for_status()
    result = response.json()

    if result.get("code") != "Ok":
        return [start_coord, end_coord], 0

    geometry = result["routes"][0]["geometry"]["coordinates"]  # [lon, lat]
    duration_sec = result["routes"][0]["duration"]

    route_points = [(lat, lon) for lon, lat in geometry]
    return route_points, duration_sec


@st.cache_data(show_spinner=False)
def get_full_osrm_route(route):
    """
    Gabungkan semua segmen OSRM untuk 1 kendaraan.
    """
    coords = route["Coordinates"]
    all_points = []
    segment_durations = []

    for i in range(len(coords) - 1):
        segment_points, duration_sec = get_osrm_route_geometry(coords[i], coords[i + 1])

        if i > 0 and len(segment_points) > 0:
            segment_points = segment_points[1:]

        all_points.extend(segment_points)
        segment_durations.append(duration_sec)

    return all_points, segment_durations

def create_route_map(route):
    """Create route map that follows actual OSRM road geometry."""
    route_colors = ["#FF0000", "#0000FF", "#008000", "#FFA500", "#800080"]
    route_color = route_colors[(route["Vehicle"] - 1) % len(route_colors)]

    road_points, _ = get_full_osrm_route(route)

    route_map = folium.Map(
        location=route["Coordinates"][0],
        zoom_start=13,
        control_scale=True
    )

    # Marker setiap stop
    for idx, stop in enumerate(route["Schedule"]):
        if idx == 0:
            icon_color = "green"
            icon_label = "home"
        elif idx == len(route["Schedule"]) - 1:
            icon_color = "red"
            icon_label = "flag"
        else:
            icon_color = "blue"
            icon_label = "info-sign"

        folium.Marker(
            location=[stop["Latitude"], stop["Longitude"]],
            tooltip=f"{stop['Campus']} - {stop['Time']}",
            popup=(
                f"<b>{stop['Campus']}</b><br>"
                f"Arrival: {stop['Time']}<br>"
                f"Vehicle: {route['Vehicle']}"
            ),
            icon=folium.Icon(color=icon_color, icon=icon_label)
        ).add_to(route_map)

    # Route line mengikuti jalan asli
    AntPath(
        locations=road_points,
        color=route_color,
        weight=6,
        opacity=0.9,
        delay=800
    ).add_to(route_map)

    return route_map

def create_combined_route_map(routes):
    """Create combined map with actual OSRM road geometry."""
    route_colors = ["#FF0000", "#0000FF", "#008000", "#FFA500", "#800080"]

    combined_map = folium.Map(
        location=routes[0]["Coordinates"][0],
        zoom_start=13,
        control_scale=True
    )

    for route in routes:
        route_color = route_colors[(route["Vehicle"] - 1) % len(route_colors)]
        road_points, _ = get_full_osrm_route(route)

        AntPath(
            locations=road_points,
            color=route_color,
            weight=6,
            opacity=0.9,
            delay=800
        ).add_to(combined_map)

        for idx, stop in enumerate(route["Schedule"]):
            folium.Marker(
                location=[stop["Latitude"], stop["Longitude"]],
                tooltip=f"Vehicle {route['Vehicle']} - {stop['Campus']} - {stop['Time']}",
                popup=(
                    f"<b>Vehicle {route['Vehicle']}</b><br>"
                    f"{stop['Campus']}<br>"
                    f"Arrival: {stop['Time']}"
                ),
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(combined_map)

    return combined_map

# --- SIDEBAR: OPERATIONAL PARAMETERS & SCENARIOS ---
st.sidebar.header("⚙️ Operational Scenarios")
scenario = st.sidebar.selectbox(
    "Select Scenario",
    ["Normal examination day", "Peak examination day", "Delayed departure"]
)

st.sidebar.header("🚚 Fleet Parameters")
num_vehicles = st.sidebar.number_input(
    "Number of Vehicles",
    min_value=1,
    max_value=10,
    value=3
)

vehicle_capacity = st.sidebar.number_input(
    "Vehicle Capacity (Packages)",
    min_value=50,
    max_value=500,
    value=100
)

st.sidebar.header("📦 Base Demand Input")
st.sidebar.caption("Enter base demand. It will adjust automatically based on the scenario.")

demand_D = st.sidebar.number_input("Campus D", min_value=0, value=48)
demand_G = st.sidebar.number_input("Campus G", min_value=0, value=30)
demand_F4 = st.sidebar.number_input("Campus F4", min_value=0, value=18)
demand_F5 = st.sidebar.number_input("Campus F5", min_value=0, value=12)
demand_F6 = st.sidebar.number_input("Campus F6", min_value=0, value=15)
demand_F7 = st.sidebar.number_input("Campus F7", min_value=0, value=10)
demand_F8 = st.sidebar.number_input("Campus F8", min_value=0, value=6)


# --- EXECUTION BUTTON ---
if st.button("🚀 Run Route Optimization", type="primary", use_container_width=True):
    with st.spinner("Downloading road-network data from OSRM and optimizing routes..."):

        # Apply Scenario Multipliers
        if scenario == "Normal examination day":
            demand_multiplier = 1.00
            depot_start = 360  # 06:00
        elif scenario == "Peak examination day":
            demand_multiplier = 1.25  # 25% demand increase
            depot_start = 360
        elif scenario == "Delayed departure":
            demand_multiplier = 1.00
            depot_start = 375  # 06:15
        else:
            demand_multiplier = 1.00
            depot_start = 360

        # 1. PREPARE DATA MODEL
        data = {}

        data["address_list"] = [
            "Campus E (Depot)",
            "Campus D",
            "Campus G",
            "Campus F4",
            "Campus F5",
            "Campus F6",
            "Campus F7",
            "Campus F8"
        ]

        data["raw_coords"] = [
            (-6.353752, 106.841593),
            (-6.367957, 106.833096),
            (-6.354235, 106.843384),
            (-6.373650, 106.863186),
            (-6.369296, 106.836768),
            (-6.345757, 106.854354),
            (-6.344363, 106.883077),
            (-6.369801, 106.839587)
        ]

        data["demands"] = [
            0,
            math.ceil(demand_D * demand_multiplier),
            math.ceil(demand_G * demand_multiplier),
            math.ceil(demand_F4 * demand_multiplier),
            math.ceil(demand_F5 * demand_multiplier),
            math.ceil(demand_F6 * demand_multiplier),
            math.ceil(demand_F7 * demand_multiplier),
            math.ceil(demand_F8 * demand_multiplier)
        ]

        data["vehicle_capacities"] = [int(vehicle_capacity)] * int(num_vehicles)
        data["num_vehicles"] = int(num_vehicles)
        data["depot"] = 0
        data["depot_start"] = depot_start

        # Time windows: Depot Start-08:30, Exam Sites 06:30-07:30
        data["time_windows"] = [(depot_start, 510)] + [(390, 450)] * 7
        data["service_times"] = [15, 15, 10, 10, 10, 10, 10, 10]

        # Feasibility check
        total_demand = sum(data["demands"])
        total_capacity = sum(data["vehicle_capacities"])

        if total_demand > total_capacity:
            st.error(
                f"❌ Infeasible capacity setting: Total demand is {total_demand} packages, "
                f"but total fleet capacity is only {total_capacity} packages."
            )
            st.stop()

        # Fetch OSRM Matrix
        try:
            data = get_osrm_matrices(data)
        except Exception:
            st.error("Failed to connect to OSRM server. Please check your internet connection.")
            st.stop()

        # Run CVRPTW Solver
        result = solve_cvrptw(data)

        if result is None:
            st.error("❌ No feasible solution found.")
            st.warning(
                "**Infeasibility Analysis:**\n"
                "1. The number of vehicles may be insufficient for the total demand.\n"
                "2. The delivery time windows may be too narrow, causing lateness.\n\n"
                "Suggestion: Increase the number of vehicles, increase vehicle capacity, "
                "or relax the time-window constraints."
            )
            st.stop()

        st.session_state.optimization_result = result
        st.session_state.optimization_data = data
        st.session_state.optimization_metrics = {
            "total_demand": total_demand,
            "total_capacity": total_capacity,
            "scenario": scenario
        }

        # 2. DISPLAY RESULTS

if st.session_state.optimization_result is not None:
    result = st.session_state.optimization_result
    data = st.session_state.optimization_data
    total_demand = st.session_state.optimization_metrics["total_demand"]
    total_capacity = st.session_state.optimization_metrics["total_capacity"]
    saved_scenario = st.session_state.optimization_metrics["scenario"]

    st.success("✅ Optimized route successfully generated!")

    optimized_distance = result["optimized_distance_km"]

    baseline_route = [0, 1, 4, 7, 3, 5, 6, 2, 0]
    baseline_distance = calculate_route_distance(
        baseline_route,
        data["distance_matrix"]
    ) / 1000

    improvement = ((baseline_distance - optimized_distance) / baseline_distance) * 100

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Baseline (1-Vehicle TSP)", f"{baseline_distance:.2f} km")
    col2.metric(
        "Optimized Distance",
        f"{optimized_distance:.2f} km",
        f"{improvement:.2f}% improvement"
    )
    col3.metric("Total Delivered", f"{total_demand} packages")
    col4.metric("Capacity Utilization", f"{(total_demand / total_capacity) * 100:.1f}%")

    st.markdown("---")
    st.subheader("Route Details per Vehicle")

    st.markdown("### Combined Optimized Route Map")
    combined_map = create_combined_route_map(result["route_results"])
    st_folium(
        combined_map,
        width=1000,
        height=500,
        key="combined_route_map"
    )
    for route in result["route_results"]:
        with st.expander(
            f"🚛 Vehicle {route['Vehicle']} - Distance: {route['Distance (km)']} km | "
            f"Delivered: {route['Delivered Packages']} packages",
            expanded=True
        ):
            if "Schedule" in route:
                schedule_text = "\n".join(
                    [f"{stop['Campus']} {stop['Time']}" for stop in route["Schedule"]]
                )
                st.code(schedule_text)
            else:
                st.markdown(route["Route"])

            if "Coordinates" in route:
                route_map = create_route_map(route)
                st_folium(
                    route_map,
                    width=1000,
                    height=450,
                    key=f"route_map_{route['Vehicle']}"
                )

    st.markdown("---")

    latest_actual_arrival = result["latest_actual_arrival"]
    time_buffer = 450 - latest_actual_arrival

    st.info(
        f"⏰ **Delivery Deadline Assessment:** The latest delivery occurred at "
        f"**{latest_actual_arrival // 60:02d}:{latest_actual_arrival % 60:02d}**, "
        f"leaving a safety buffer of **{time_buffer} minutes** before the 07:30 AM deadline."
    )

    result_df = pd.DataFrame(result["route_results"])

    st.markdown("### Route Summary Table")
    st.dataframe(result_df, use_container_width=True)

    stop_df = pd.DataFrame(result["stop_results"])

    st.markdown("### Stop-Level Delivery Table")
    st.dataframe(stop_df, use_container_width=True)

    csv_result = result_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="📥 Download Route Results as CSV",
        data=csv_result,
        file_name=f"exam_cvrptw_results_{saved_scenario.replace(' ', '_')}.csv",
        mime="text/csv"
    )
