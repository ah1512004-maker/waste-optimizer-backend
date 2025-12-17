# confirm_server.py
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import math
from copy import deepcopy

app = Flask(__name__)
CORS(app)  # allow requests from any origin (localhost:5500, mobile, ...)

# ------------------------------------------------------------
# Configuration (based on the provided optimization + simulation spec)
# - Optimization uses alpha only (average unit energy consumption)
# - Simulation uses alpha + beta * current_load for per-segment energy
# - Battery and capacity safety thresholds are enforced
# ------------------------------------------------------------
ALPHA_KWH_PER_KM = 0.86
BETA_KWH_PER_KG_KM = ALPHA_KWH_PER_KM / 10000  # example extension for realism
MAX_BATTERY_KWH = 100.0
MIN_BATTERY_KWH = 20.0
MAX_LOAD_KG = 5000.0

DEPOT_NAME = "Parking"  # depot node name in routes

# ------------------------------------------------------------
# Coordinates (TEMPORARY demo coordinates)
# Replace these with real GPS coords or use a distance matrix later.
# Keys MUST match your node strings in routes (e.g., "61", "31", ...).
# ------------------------------------------------------------
COORDS = {
    "Parking": (40.996301, 28.884600),  # depot (example)
    "61": (40.9970, 28.8850),
    "31": (40.9980, 28.8860),
    "12": (40.9990, 28.8870),
    "18": (41.0000, 28.8880),
    "22": (40.9950, 28.8830),
    "35": (40.9940, 28.8820),
    "44": (40.9930, 28.8810),
    "52": (40.9920, 28.8800),
    "70": (40.9910, 28.8790),
    "81": (40.9900, 28.8780),
    "99": (40.9890, 28.8770),
}

# ------------------------------------------------------------
# Mock data for routes and zones
# NOTE: In your real project, these will come from your optimizer output.
# ------------------------------------------------------------
routes = [
    {
        "truckId": 1,
        "nodeSequence": ["Parking", "61", "31", "12", "18", "Parking"],
        "totalDistanceKm": 18.4,
        "totalEnergyKWh": 20.2,
        "totalCollectedWeightKg": 140.0,
        "status": "Pending",  # Pending | InProgress | Collected
    },
    {
        "truckId": 2,
        "nodeSequence": ["Parking", "22", "35", "44", "Parking"],
        "totalDistanceKm": 15.1,
        "totalEnergyKWh": 16.6,
        "totalCollectedWeightKg": 105.0,
        "status": "Pending",
    },
    {
        "truckId": 3,
        "nodeSequence": ["Parking", "52", "70", "81", "99", "Parking"],
        "totalDistanceKm": 21.7,
        "totalEnergyKWh": 23.9,
        "totalCollectedWeightKg": 140.0,
        "status": "Pending",
    },
]

# IMPORTANT: give each zone a unique integer id so we can confirm it reliably
zones = [
    # Truck 1
    {"id": 101, "truckId": 1, "zone": "Zone A1", "binId": 61, "fillLevelPercent": 80, "estimatedWeightKg": 35.0, "status": "Pending"},
    {"id": 102, "truckId": 1, "zone": "Zone A2", "binId": 31, "fillLevelPercent": 60, "estimatedWeightKg": 30.0, "status": "Pending"},
    {"id": 103, "truckId": 1, "zone": "Zone B1", "binId": 12, "fillLevelPercent": 75, "estimatedWeightKg": 40.0, "status": "Pending"},
    {"id": 104, "truckId": 1, "zone": "Zone B2", "binId": 18, "fillLevelPercent": 50, "estimatedWeightKg": 35.0, "status": "Pending"},

    # Truck 2
    {"id": 201, "truckId": 2, "zone": "Zone C1", "binId": 22, "fillLevelPercent": 70, "estimatedWeightKg": 35.0, "status": "Pending"},
    {"id": 202, "truckId": 2, "zone": "Zone C2", "binId": 35, "fillLevelPercent": 65, "estimatedWeightKg": 35.0, "status": "Pending"},
    {"id": 203, "truckId": 2, "zone": "Zone D1", "binId": 44, "fillLevelPercent": 55, "estimatedWeightKg": 35.0, "status": "Pending"},

    # Truck 3
    {"id": 301, "truckId": 3, "zone": "Zone D2", "binId": 52, "fillLevelPercent": 85, "estimatedWeightKg": 35.0, "status": "Pending"},
    {"id": 302, "truckId": 3, "zone": "Zone E1", "binId": 70, "fillLevelPercent": 90, "estimatedWeightKg": 35.0, "status": "Pending"},
    {"id": 303, "truckId": 3, "zone": "Zone E2", "binId": 81, "fillLevelPercent": 65, "estimatedWeightKg": 35.0, "status": "Pending"},
    {"id": 304, "truckId": 3, "zone": "Zone F1", "binId": 99, "fillLevelPercent": 40, "estimatedWeightKg": 35.0, "status": "Pending"},
]

# ------------------------------------------------------------
# Server-side truck state (Digital Twin)
# This is the "source of truth" for live status shown in dashboard.
# ------------------------------------------------------------
truck_state = {}  # truckId -> state dict


def init_truck_state_if_needed(truck_id: int, reset: bool = False):
    """Initialize truck state once (or reset if requested)."""
    if reset or (truck_id not in truck_state):
        truck_state[truck_id] = {
            "truckId": truck_id,
            "currentLocation": DEPOT_NAME,
            "cumDistanceKm": 0.0,
            "cumCollectedWeightKg": 0.0,
            "cumEnergyKWh": 0.0,
            "batteryKWh": MAX_BATTERY_KWH,
            "fillRatio": 0.0,
            "efficiencyKWhPerKg": 0.0,
            "rangeLeftKm": (MAX_BATTERY_KWH / ALPHA_KWH_PER_KM) * 0.8,  # 20% safety margin
            "status": "IDLE",  # IDLE | COLLECTING | EMERGENCY_RETURN | CAPACITY_RETURN | DONE
        }


def reset_all_states():
    """Reset all truck states and all zone/route statuses."""
    truck_state.clear()
    for z in zones:
        z["status"] = "Pending"
    for r in routes:
        r["status"] = "Pending"
    for r in routes:
        init_truck_state_if_needed(r["truckId"], reset=True)


def get_route_for_truck(truck_id: int):
    for r in routes:
        if r.get("truckId") == truck_id:
            return r
    return None


def get_zones_for_truck(truck_id: int):
    return [z for z in zones if z.get("truckId") == truck_id]


def update_route_status(truck_id: int):
    """Update route status based on zone completion."""
    route = get_route_for_truck(truck_id)
    if not route:
        return
    truck_zones = get_zones_for_truck(truck_id)
    if all(z.get("status") == "Collected" for z in truck_zones):
        route["status"] = "Collected"
    elif any(z.get("status") == "Collected" for z in truck_zones):
        route["status"] = "InProgress"
    else:
        route["status"] = "Pending"


def next_pending_zone_for_truck(truck_id: int):
    """
    Determine the next pending zone based on the route nodeSequence order.
    We look at the route, then find the first binId in nodeSequence that is still Pending.
    """
    route = get_route_for_truck(truck_id)
    if not route:
        return None

    ordered_bins = []
    for node in route.get("nodeSequence", []):
        if node == DEPOT_NAME:
            continue
        try:
            ordered_bins.append(int(node))
        except ValueError:
            continue

    truck_zones = get_zones_for_truck(truck_id)

    for bin_id in ordered_bins:
        for z in truck_zones:
            if z.get("binId") == bin_id and z.get("status") == "Pending":
                return z

    return None


# ------------------------------------------------------------
# Distance + Energy Model (Simulation)
# ------------------------------------------------------------
def haversine_km(coord1, coord2) -> float:
    """Great-circle distance between two (lat, lon) points in kilometers."""
    R = 6371.0
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def calculate_distance_km(current_loc: str, next_loc: str) -> float:
    """
    Distance provider.
    - Preferred: real coordinates (Haversine for demo)
    - Later: replace with Dist[i][j] matrix or OSRM/Google routing
    """
    if current_loc not in COORDS or next_loc not in COORDS:
        return 2.5  # fallback demo distance
    return haversine_km(COORDS[current_loc], COORDS[next_loc])


def calculate_energy_kwh(distance_km: float, current_carried_weight_kg: float) -> float:
    """
    Segment energy consumption:
      base = alpha * distance
      load-dependent = beta * distance * current_load
    NOTE: current_load should be the load BEFORE collecting at the next container.
    """
    base = ALPHA_KWH_PER_KM * distance_km
    weight_part = BETA_KWH_PER_KG_KM * distance_km * current_carried_weight_kg
    return base + weight_part


def update_kpis(state: dict):
    """Recompute KPIs after each step."""
    state["fillRatio"] = state["cumCollectedWeightKg"] / MAX_LOAD_KG if MAX_LOAD_KG > 0 else 0.0
    denom = max(state["cumCollectedWeightKg"], 1.0)
    state["efficiencyKWhPerKg"] = state["cumEnergyKWh"] / denom
    state["rangeLeftKm"] = (state["batteryKWh"] / ALPHA_KWH_PER_KM) * 0.8  # 20% safety margin


# ------------------------------------------------------------
# Incremental Per-Bin Simulation Engine (Digital Twin)
# - Walk along route segment-by-segment
# - Consume energy based on (alpha + beta*load)
# - Update battery/load and apply safety checks
# ------------------------------------------------------------
def simulate_truck_full_route(truck_id: int, reset: bool = False) -> dict:
    """
    Simulate a single truck from depot through its route and back to depot.
    Returns a detailed timeline + final metrics.
    """
    init_truck_state_if_needed(truck_id, reset=reset)

    route = get_route_for_truck(truck_id)
    if not route:
        return {"error": f"Route not found for truckId={truck_id}"}

    state = truck_state[truck_id]
    timeline = []

    node_seq = route.get("nodeSequence", [])
    if not node_seq or node_seq[0] != DEPOT_NAME or node_seq[-1] != DEPOT_NAME:
        return {"error": "Route must start and end with depot node name"}

    # Ensure we start from depot for this simulation
    state["currentLocation"] = DEPOT_NAME
    state["status"] = "COLLECTING"
    update_kpis(state)

    # Helper to get zone by binId for this truck
    truck_zones = get_zones_for_truck(truck_id)
    zone_by_bin = {int(z["binId"]): z for z in truck_zones}

    for step_idx in range(len(node_seq) - 1):
        src = str(node_seq[step_idx])
        dst = str(node_seq[step_idx + 1])

        # Compute segment distance and energy using load BEFORE collecting at dst
        distance_km = calculate_distance_km(src, dst)
        energy_kwh = calculate_energy_kwh(distance_km, state["cumCollectedWeightKg"])

        # Battery safety check
        if state["batteryKWh"] - energy_kwh < MIN_BATTERY_KWH:
            state["status"] = "EMERGENCY_RETURN"
            timeline.append({
                "truckId": truck_id,
                "step": step_idx,
                "from": src,
                "to": dst,
                "distanceKm": distance_km,
                "energyKWh": energy_kwh,
                "event": "BATTERY_EMERGENCY_RETURN",
                "batteryKWhBefore": state["batteryKWh"],
                "batteryKWhAfter": state["batteryKWh"],
                "loadKg": state["cumCollectedWeightKg"],
            })
            break

        # Apply travel updates
        battery_before = state["batteryKWh"]
        state["cumDistanceKm"] += distance_km
        state["cumEnergyKWh"] += energy_kwh
        state["batteryKWh"] -= energy_kwh
        state["currentLocation"] = dst

        event = "TRAVEL"

        # If dst is a container (not depot), collect waste after arriving
        if dst != DEPOT_NAME:
            try:
                bin_id = int(dst)
            except ValueError:
                bin_id = None

            if bin_id is not None and bin_id in zone_by_bin:
                z = zone_by_bin[bin_id]

                if z["status"] == "Pending":
                    collected_weight = float(z.get("estimatedWeightKg", 0.0))
                    state["cumCollectedWeightKg"] += collected_weight
                    z["status"] = "Collected"
                    event = "COLLECTED_BIN"
                    update_route_status(truck_id)

                    # Capacity safety check after collecting
                    if state["cumCollectedWeightKg"] > MAX_LOAD_KG:
                        state["status"] = "CAPACITY_RETURN"
                        timeline.append({
                            "truckId": truck_id,
                            "step": step_idx,
                            "from": src,
                            "to": dst,
                            "distanceKm": distance_km,
                            "energyKWh": energy_kwh,
                            "event": "CAPACITY_EXCEEDED_RETURN",
                            "batteryKWhBefore": battery_before,
                            "batteryKWhAfter": state["batteryKWh"],
                            "loadKg": state["cumCollectedWeightKg"],
                            "zoneId": z["id"],
                            "binId": z["binId"],
                        })
                        break

        update_kpis(state)

        timeline.append({
            "truckId": truck_id,
            "step": step_idx,
            "from": src,
            "to": dst,
            "distanceKm": distance_km,
            "energyKWh": energy_kwh,
            "event": event,
            "batteryKWhBefore": battery_before,
            "batteryKWhAfter": state["batteryKWh"],
            "loadKg": state["cumCollectedWeightKg"],
            "fillRatio": state["fillRatio"],
            "efficiencyKWhPerKg": state["efficiencyKWhPerKg"],
            "rangeLeftKm": state["rangeLeftKm"],
        })

    # Finalize status
    truck_zones = get_zones_for_truck(truck_id)
    if state["status"] not in {"EMERGENCY_RETURN", "CAPACITY_RETURN"}:
        if all(z["status"] == "Collected" for z in truck_zones):
            state["status"] = "DONE"
            update_route_status(truck_id)

    return {
        "truckId": truck_id,
        "finalState": state,
        "route": route,
        "zones": truck_zones,
        "timeline": timeline,
    }


def simulate_fleet(reset: bool = False) -> dict:
    """
    Simulate all trucks (fleet).
    Returns per-truck simulation outputs.
    """
    outputs = []
    for r in routes:
        tid = r["truckId"]
        outputs.append(simulate_truck_full_route(tid, reset=reset))
    return {"fleet": outputs}


# ------------------------------------------------------------
# API endpoints
# ------------------------------------------------------------
@app.route("/")
def index():
    return jsonify({"message": "Confirm server is running"})


@app.route("/routes", methods=["GET"])
def get_routes():
    """Return all routes for drivers page."""
    for r in routes:
        init_truck_state_if_needed(r["truckId"])
    return jsonify(routes)


@app.route("/zones", methods=["GET"])
def get_zones():
    """
    Return ALL zones (global list).
    Optional query param: ?truckId=1
    """
    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify(zones)
    return jsonify([z for z in zones if z.get("truckId") == truck_id])


@app.route("/truck-state", methods=["GET"])
def get_truck_state():
    """Return live server-side truck state for dashboard."""
    for r in routes:
        init_truck_state_if_needed(r["truckId"])

    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify(list(truck_state.values()))
    if truck_id not in truck_state:
        init_truck_state_if_needed(truck_id)
    return jsonify(truck_state[truck_id])


@app.route("/driver")
def driver_page():
    """Serve the driver web page."""
    return send_from_directory("driver_web", "index.html")


@app.route("/confirm-zone", methods=["POST"])
def confirm_zone():
    """
    Manual confirmation (zone-by-zone).

    Body:
      {
        "truckId": 1,
        "zoneId": 101
      }

    Rules:
    - Zone must belong to truck
    - Zone must be the NEXT pending zone in the truck route order
    - Update zone status, update truck state, update route status
    """
    data = request.get_json() or {}
    truck_id = data.get("truckId")
    zone_id = data.get("zoneId")

    if truck_id is None or zone_id is None:
        return jsonify({"error": "truckId and zoneId are required"}), 400

    init_truck_state_if_needed(truck_id)

    route = get_route_for_truck(truck_id)
    if not route:
        return jsonify({"error": "Route not found for this truckId"}), 404

    zone = None
    for z in zones:
        if z.get("id") == zone_id:
            zone = z
            break
    if not zone:
        return jsonify({"error": "Zone not found"}), 404

    if zone.get("truckId") != truck_id:
        return jsonify({"error": "Zone does not belong to this truckId"}), 400

    if zone.get("status") != "Pending":
        return jsonify({"error": "Zone is not Pending"}), 400

    expected = next_pending_zone_for_truck(truck_id)
    if not expected:
        return jsonify({"error": "No pending zones left for this truck"}), 400
    if expected.get("id") != zone_id:
        return jsonify({
            "error": "This is not the next pending zone in the route order",
            "expectedNextZoneId": expected.get("id"),
            "expectedNextBinId": expected.get("binId"),
        }), 400

    # Simulate travel to the bin and collect it (incremental logic)
    state = truck_state[truck_id]

    distance_km = calculate_distance_km(state["currentLocation"], str(zone["binId"]))
    energy_kwh = calculate_energy_kwh(distance_km, state["cumCollectedWeightKg"])

    if state["batteryKWh"] - energy_kwh < MIN_BATTERY_KWH:
        return jsonify({
            "error": "Battery would drop below MIN_BATTERY after this move",
            "batteryKWh": state["batteryKWh"],
            "neededEnergyKWh": energy_kwh,
            "minBatteryKWh": MIN_BATTERY_KWH
        }), 400

    state["cumDistanceKm"] += distance_km
    state["cumEnergyKWh"] += energy_kwh
    state["batteryKWh"] -= energy_kwh

    collected_weight = float(zone.get("estimatedWeightKg", 0.0))
    state["cumCollectedWeightKg"] += collected_weight

    if state["cumCollectedWeightKg"] > MAX_LOAD_KG:
        state["status"] = "CAPACITY_RETURN"
        return jsonify({
            "error": "Capacity exceeded after collecting this zone",
            "cumCollectedWeightKg": state["cumCollectedWeightKg"],
            "maxLoadKg": MAX_LOAD_KG
        }), 400

    state["currentLocation"] = str(zone["binId"])
    state["status"] = "COLLECTING"
    update_kpis(state)

    zone["status"] = "Collected"
    update_route_status(truck_id)

    return jsonify({
        "message": "Zone confirmed and state updated successfully",
        "truckState": state,
        "zone": zone,
        "route": get_route_for_truck(truck_id),
    })


@app.route("/confirm-route", methods=["POST"])
def confirm_route():
    """
    OPTIONAL (demo helper):
    Mark a truck route as collected AND update all its remaining zones to Collected.

    Body: { "truckId": 1 }
    """
    data = request.get_json() or {}
    truck_id = data.get("truckId")

    if truck_id is None:
        return jsonify({"error": "truckId is required"}), 400

    init_truck_state_if_needed(truck_id)

    route = get_route_for_truck(truck_id)
    if not route:
        return jsonify({"error": "Route not found"}), 404

    for z in zones:
        if z.get("truckId") == truck_id:
            z["status"] = "Collected"

    update_route_status(truck_id)

    # Also mark digital-twin state as done
    st = truck_state[truck_id]
    st["status"] = "DONE"
    update_kpis(st)

    return jsonify({"message": "Route and zones updated successfully", "route": route, "truckState": st})


# ------------------------------------------------------------
# NEW: Simulation endpoints (run the equations automatically)
# ------------------------------------------------------------
@app.route("/simulate", methods=["POST"])
def simulate_endpoint():
    """
    Run incremental per-bin simulation.
    Body examples:
      { "truckId": 1, "reset": true }
      { "reset": true }   -> simulate whole fleet
    """
    data = request.get_json() or {}
    reset = bool(data.get("reset", False))
    truck_id = data.get("truckId", None)

    if reset:
        reset_all_states()

    if truck_id is not None:
        try:
            truck_id = int(truck_id)
        except ValueError:
            return jsonify({"error": "truckId must be an integer"}), 400
        out = simulate_truck_full_route(truck_id, reset=False)
        return jsonify(out)

    out = simulate_fleet(reset=False)
    return jsonify(out)


@app.route("/reset", methods=["POST"])
def reset_endpoint():
    """Reset all zones/routes and all truck digital-twin states."""
    reset_all_states()
    return jsonify({"message": "Reset done", "routes": routes, "zones": zones, "truckState": list(truck_state.values())})


# Render / gunicorn entrypoint
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
