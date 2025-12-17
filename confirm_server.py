from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # allow requests from any origin (localhost:5500, mobile, ...)

# -----------------------------
# Configuration (from your PDF assumptions)
# -----------------------------
ALPHA_KWH_PER_KM = 0.86
BETA_KWH_PER_KG_KM = ALPHA_KWH_PER_KM / 10000  # example extension
MAX_BATTERY_KWH = 100.0
MIN_BATTERY_KWH = 20.0
MAX_LOAD_KG = 5000.0

DEPOT_NAME = "Parking"  # you used "Parking" in routes


# -----------------------------
# Mock data for routes and zones
# -----------------------------
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


# -----------------------------
# Server-side truck state (Digital Twin)
# -----------------------------
# This is the "source of truth" for live status shown in dashboard.
truck_state = {}  # truckId -> state dict


def init_truck_state_if_needed(truck_id: int):
    """Initialize truck state once (or reset if you want)."""
    if truck_id not in truck_state:
        truck_state[truck_id] = {
            "truckId": truck_id,
            "currentLocation": DEPOT_NAME,
            "cumDistanceKm": 0.0,
            "cumCollectedWeightKg": 0.0,
            "cumEnergyKWh": 0.0,
            "batteryKWh": MAX_BATTERY_KWH,
            "fillRatio": 0.0,
            "efficiencyKWhPerKg": 0.0,
            "rangeLeftKm": (MAX_BATTERY_KWH / ALPHA_KWH_PER_KM) * 0.8,  # with safety margin
        }


def get_route_for_truck(truck_id: int):
    for r in routes:
        if r.get("truckId") == truck_id:
            return r
    return None


def get_zones_for_truck(truck_id: int):
    return [z for z in zones if z.get("truckId") == truck_id]


def next_pending_zone_for_truck(truck_id: int):
    """
    Determine the next pending zone based on the route nodeSequence order.
    We look at the route, then find the first binId in nodeSequence that is still Pending.
    """
    route = get_route_for_truck(truck_id)
    if not route:
        return None

    # Extract the ordered binIds from the route excluding depot
    ordered_bins = []
    for node in route.get("nodeSequence", []):
        if node == DEPOT_NAME:
            continue
        try:
            ordered_bins.append(int(node))
        except ValueError:
            # if node isn't numeric, ignore
            continue

    truck_zones = get_zones_for_truck(truck_id)

    # Find first pending zone in route order
    for bin_id in ordered_bins:
        for z in truck_zones:
            if z.get("binId") == bin_id and z.get("status") == "Pending":
                return z

    return None


def calculate_distance_km(current_loc: str, next_bin_id: int) -> float:
    """
    Placeholder distance function.
    Replace this with:
      - Dist[i][j] from your dataset, or
      - Haversine between GPS coords, etc.
    """
    # Simple mock: fixed distance per hop
    return 2.5


def calculate_energy_kwh(distance_km: float, current_carried_weight_kg: float) -> float:
    base = ALPHA_KWH_PER_KM * distance_km
    weight_part = BETA_KWH_PER_KG_KM * distance_km * current_carried_weight_kg
    return base + weight_part


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


# -----------------------------
# API endpoints
# -----------------------------
@app.route("/")
def index():
    return jsonify({"message": "Confirm server is running"})


@app.route("/routes", methods=["GET"])
def get_routes():
    """Return all routes for drivers page."""
    # Ensure states exist for trucks
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
    # Ensure states exist for trucks
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
    # serve the driver web page
    return send_from_directory("driver_web", "index.html")


@app.route("/confirm-zone", methods=["POST"])
def confirm_zone():
    """
    Manual confirmation (zone-by-zone). This matches your project agreement.

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

    # Find the zone
    zone = None
    for z in zones:
        if z.get("id") == zone_id:
            zone = z
            break
    if not zone:
        return jsonify({"error": "Zone not found"}), 404

    # Validate ownership
    if zone.get("truckId") != truck_id:
        return jsonify({"error": "Zone does not belong to this truckId"}), 400

    # Validate it is pending
    if zone.get("status") != "Pending":
        return jsonify({"error": "Zone is not Pending"}), 400

    # Validate it is the next pending zone by route order
    expected = next_pending_zone_for_truck(truck_id)
    if not expected:
        return jsonify({"error": "No pending zones left for this truck"}), 400
    if expected.get("id") != zone_id:
        return jsonify({
            "error": "This is not the next pending zone in the route order",
            "expectedNextZoneId": expected.get("id"),
            "expectedNextBinId": expected.get("binId"),
        }), 400

    # --- Simulate traveling to that bin and collecting it (server-side state updates) ---
    state = truck_state[truck_id]

    distance_km = calculate_distance_km(state["currentLocation"], zone["binId"])
    energy_kwh = calculate_energy_kwh(distance_km, state["cumCollectedWeightKg"])

    # Battery safety check
    if state["batteryKWh"] - energy_kwh < MIN_BATTERY_KWH:
        return jsonify({
            "error": "Battery would drop below MIN_BATTERY after this move",
            "batteryKWh": state["batteryKWh"],
            "neededEnergyKWh": energy_kwh,
            "minBatteryKWh": MIN_BATTERY_KWH
        }), 400

    # Move updates
    state["cumDistanceKm"] += distance_km
    state["cumEnergyKWh"] += energy_kwh
    state["batteryKWh"] -= energy_kwh

    # Collection updates (manual confirm happens NOW)
    collected_weight = float(zone.get("estimatedWeightKg", 0.0))
    state["cumCollectedWeightKg"] += collected_weight

    # Capacity check
    if state["cumCollectedWeightKg"] > MAX_LOAD_KG:
        return jsonify({
            "error": "Capacity exceeded after collecting this zone",
            "cumCollectedWeightKg": state["cumCollectedWeightKg"],
            "maxLoadKg": MAX_LOAD_KG
        }), 400

    # Update instantaneous KPIs
    state["fillRatio"] = state["cumCollectedWeightKg"] / MAX_LOAD_KG if MAX_LOAD_KG > 0 else 0.0
    denom = max(state["cumCollectedWeightKg"], 1.0)
    state["efficiencyKWhPerKg"] = state["cumEnergyKWh"] / denom
    state["rangeLeftKm"] = (state["batteryKWh"] / ALPHA_KWH_PER_KM) * 0.8

    # Update location to the bin (as string)
    state["currentLocation"] = str(zone["binId"])

    # Mark zone collected
    zone["status"] = "Collected"

    # Update route status (Pending/InProgress/Collected)
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

    NOTE:
    If you want strict zone-by-zone only, you can delete this endpoint.
    """
    data = request.get_json() or {}
    truck_id = data.get("truckId")

    if truck_id is None:
        return jsonify({"error": "truckId is required"}), 400

    init_truck_state_if_needed(truck_id)

    route = get_route_for_truck(truck_id)
    if not route:
        return jsonify({"error": "Route not found"}), 404

    # Mark all zones for this truck as collected (without travel simulation)
    for z in zones:
        if z.get("truckId") == truck_id:
            z["status"] = "Collected"

    update_route_status(truck_id)

    return jsonify({"message": "Route and zones updated successfully", "route": route})


# Render / gunicorn entrypoint
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
