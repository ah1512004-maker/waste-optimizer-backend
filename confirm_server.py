from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# -----------------------------
# Configuration / constants
# -----------------------------
ALPHA_KWH_PER_KM = 0.86
BETA_KWH_PER_KG_KM = ALPHA_KWH_PER_KM / 10000  # simple extension (demo)
MAX_BATTERY_KWH = 100.0
MIN_BATTERY_KWH = 20.0
MAX_LOAD_KG = 5000.0

DEPOT_NAME = "Parking"

# -----------------------------
# Demo data (routes + zones)
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

# Each zone has a unique integer id for reliable confirmation
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
truck_state = {}  # truckId -> state dict


def init_truck_state_if_needed(truck_id: int):
    """Initialize truck state once."""
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
            "rangeLeftKm": (MAX_BATTERY_KWH / ALPHA_KWH_PER_KM) * 0.8,  # safety margin
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
    """
    route = get_route_for_truck(truck_id)
    if not route:
        return None

    # Extract ordered binIds from route (excluding depot)
    ordered_bins = []
    for node in route.get("nodeSequence", []):
        if node == DEPOT_NAME:
            continue
        try:
            ordered_bins.append(int(node))
        except ValueError:
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
    Replace with real distance matrix or GPS-based computation if needed.
    """
    return 2.5


def calculate_energy_kwh(distance_km: float, carried_weight_kg: float) -> float:
    """
    Simple energy model:
    - Base depends on distance
    - Additional depends on carried weight
    """
    base = ALPHA_KWH_PER_KM * distance_km
    weight_part = BETA_KWH_PER_KG_KM * distance_km * carried_weight_kg
    return base + weight_part


def update_route_status(truck_id: int):
    """Update route status based on zone completion."""
    route = get_route_for_truck(truck_id)
    if not route:
        return

    truck_zones = get_zones_for_truck(truck_id)
    if len(truck_zones) == 0:
        route["status"] = "Pending"
        return

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
    """Return all routes."""
    for r in routes:
        init_truck_state_if_needed(r["truckId"])
    return jsonify(routes)


@app.route("/zones", methods=["GET"])
def get_zones():
    """
    Return all zones.
    Optional query: /zones?truckId=1
    """
    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify(zones)
    return jsonify([z for z in zones if z.get("truckId") == truck_id])


@app.route("/truck-state", methods=["GET"])
def get_truck_state():
    """Return live server-side truck state."""
    for r in routes:
        init_truck_state_if_needed(r["truckId"])

    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify(list(truck_state.values()))

    init_truck_state_if_needed(truck_id)
    return jsonify(truck_state[truck_id])


@app.route("/next-zone", methods=["GET"])
def get_next_zone():
    """
    Return the next pending zone for a truck.
    Example: /next-zone?truckId=1
    """
    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify({"error": "truckId is required"}), 400

    zone = next_pending_zone_for_truck(truck_id)
    if not zone:
        return jsonify({"message": "No pending zones left for this truck", "zone": None})

    return jsonify({"zone": zone})


@app.route("/confirm-zone", methods=["POST"])
def confirm_zone():
    """
    Confirm ONE zone (bin-by-bin).
    Body:
      { "truckId": 1, "zoneId": 101 }

    Rules:
    - Zone must belong to truck
    - Zone must be the next pending zone in route order
    - Update zone status + truck state + route status
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

    # Find the zone by id
    zone = next((z for z in zones if z.get("id") == zone_id), None)
    if not zone:
        return jsonify({"error": "Zone not found"}), 404

    # Ownership validation
    if zone.get("truckId") != truck_id:
        return jsonify({"error": "Zone does not belong to this truckId"}), 400

    # Status validation
    if zone.get("status") != "Pending":
        return jsonify({"error": "Zone is not Pending"}), 400

    # Enforce next-by-route order
    expected = next_pending_zone_for_truck(truck_id)
    if not expected:
        return jsonify({"error": "No pending zones left for this truck"}), 400
    if expected.get("id") != zone_id:
        return jsonify({
            "error": "This is not the next pending zone in the route order",
            "expectedNextZoneId": expected.get("id"),
            "expectedNextBinId": expected.get("binId"),
        }), 400

    # Simulate travel + energy consumption (server-side)
    state = truck_state[truck_id]
    distance_km = calculate_distance_km(state["currentLocation"], int(zone["binId"]))
    energy_kwh = calculate_energy_kwh(distance_km, state["cumCollectedWeightKg"])

    # Battery safety check
    if state["batteryKWh"] - energy_kwh < MIN_BATTERY_KWH:
        return jsonify({
            "error": "Battery would drop below MIN_BATTERY after this move",
            "batteryKWh": state["batteryKWh"],
            "neededEnergyKWh": energy_kwh,
            "minBatteryKWh": MIN_BATTERY_KWH
        }), 400

    # Update state (movement)
    state["cumDistanceKm"] += distance_km
    state["cumEnergyKWh"] += energy_kwh
    state["batteryKWh"] -= energy_kwh

    # Update state (collection)
    collected_weight = float(zone.get("estimatedWeightKg", 0.0))
    state["cumCollectedWeightKg"] += collected_weight

    # Capacity check
    if state["cumCollectedWeightKg"] > MAX_LOAD_KG:
        return jsonify({
            "error": "Capacity exceeded after collecting this zone",
            "cumCollectedWeightKg": state["cumCollectedWeightKg"],
            "maxLoadKg": MAX_LOAD_KG
        }), 400

    # Update derived KPIs
    state["fillRatio"] = state["cumCollectedWeightKg"] / MAX_LOAD_KG if MAX_LOAD_KG > 0 else 0.0
    denom = max(state["cumCollectedWeightKg"], 1.0)
    state["efficiencyKWhPerKg"] = state["cumEnergyKWh"] / denom
    state["rangeLeftKm"] = (state["batteryKWh"] / ALPHA_KWH_PER_KM) * 0.8
    state["currentLocation"] = str(zone["binId"])

    # Mark zone collected
    zone["status"] = "Collected"

    # Update route status
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
    Demo helper:
    Mark a whole truck route as collected and set all its zones to Collected.
    Body: { "truckId": 1 }
    """
    data = request.get_json() or {}
    truck_id = data.get("truckId")

    if truck_id is None:
        return jsonify({"error": "truckId is required"}), 400

    route = get_route_for_truck(truck_id)
    if not route:
        return jsonify({"error": "Route not found"}), 404

    for z in zones:
        if z.get("truckId") == truck_id:
            z["status"] = "Collected"

    update_route_status(truck_id)
    init_truck_state_if_needed(truck_id)

    return jsonify({"message": "Route and zones updated successfully", "route": route})


@app.route("/reset", methods=["POST"])
def reset_demo():
    """
    Reset all routes/zones to Pending and clear truck_state.
    This fixes the 'always Collected' issue on Render (in-memory state).
    """
    global truck_state

    for r in routes:
        r["status"] = "Pending"

    for z in zones:
        z["status"] = "Pending"

    truck_state = {}
    return jsonify({"message": "Demo reset: all zones/routes set to Pending"}), 200

@app.route("/simulate", methods=["GET"])
def simulate():
    """
    Compatibility endpoint for the Desktop App.
    Some UI versions call /simulate to load dashboard summary + routes + zones.

    Returns:
      {
        "totalBins": int,
        "totalTrucks": int,
        "routes": [...],
        "zones": [...],
        "energyBeforeKWh": float,
        "energyAfterKWh": float,
        "savingPercent": float
      }
    """
    # Ensure truck states exist
    for r in routes:
        init_truck_state_if_needed(r["truckId"])

    total_bins = len(zones)
    total_trucks = len(routes)

    # "After" energy = current planned energy (sum of routes energy)
    energy_after = 0.0
    for r in routes:
        try:
            energy_after += float(r.get("totalEnergyKWh", 0.0))
        except Exception:
            pass

    # "Before" energy: demo baseline (you can replace with real baseline later)
    # Simple assumption: before is 1.25x after (25% worse)
    energy_before = energy_after * 1.25 if energy_after > 0 else 0.0

    saving_percent = 0.0
    if energy_before > 0:
        saving_percent = round((energy_before - energy_after) / energy_before * 100.0, 2)

    return jsonify({
        "totalBins": total_bins,
        "totalTrucks": total_trucks,
        "routes": routes,
        "zones": zones,
        "energyBeforeKWh": round(energy_before, 2),
        "energyAfterKWh": round(energy_after, 2),
        "savingPercent": saving_percent
    })

# Optional: serve driver web page locally (not used by GitHub Pages)
@app.route("/driver")
def driver_page():
    return send_from_directory("driver_web", "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
