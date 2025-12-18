from __future__ import annotations

from flask import Flask, jsonify, request
from flask_cors import CORS
from copy import deepcopy

app = Flask(__name__)
CORS(app)

# =========================================================
# Constants (from your Methodology)
# =========================================================
# Optimization uses alpha only (MILP), but simulation uses alpha + beta * load
ALPHA_KWH_PER_KM = 0.86          # kWh/km  (article-based average)
BETA_KWH_PER_KG_KM = 0.0001      # kWh/(kg*km) (project contribution)

MAX_LOAD_KG = 5000.0
BATTERY_CAPACITY_KWH = 100.0
MIN_BATTERY_KWH = 20.0

DEPOT_NAME = "Parking"

# =========================================================
# Demo distance matrix (replace with your real Dist[i][j] later)
# NOTE: Must include every node used in routes
# =========================================================
DIST_KM = {
    "Parking": {"Parking": 0.0, "61": 2.2, "31": 2.1, "12": 2.9, "18": 2.3, "22": 2.1, "35": 2.4, "44": 2.4, "52": 2.2, "70": 2.8, "81": 2.6, "99": 3.1},
    "61": {"Parking": 2.2, "31": 0.16, "12": 1.3, "18": 0.6, "52": 0.0, "70": 0.8, "81": 1.1, "99": 1.5, "22": 0.9, "35": 0.7, "44": 0.5, "61": 0.0},
    "31": {"Parking": 2.1, "61": 0.16, "12": 1.2, "18": 0.45, "22": 0.4, "35": 0.4, "44": 0.6, "31": 0.0},
    "12": {"Parking": 2.9, "31": 1.2, "18": 0.5, "12": 0.0},
    "18": {"Parking": 2.3, "12": 0.5, "18": 0.0},

    "22": {"Parking": 2.1, "35": 0.55, "44": 0.5, "22": 0.0},
    "35": {"Parking": 2.4, "22": 0.55, "44": 0.35, "35": 0.0},
    "44": {"Parking": 2.4, "22": 0.5, "35": 0.35, "44": 0.0},

    "52": {"Parking": 2.2, "70": 0.8, "81": 0.7, "99": 0.9, "52": 0.0},
    "70": {"Parking": 2.8, "52": 0.8, "81": 0.3, "99": 0.5, "70": 0.0},
    "81": {"Parking": 2.6, "52": 0.7, "70": 0.3, "99": 0.25, "81": 0.0},
    "99": {"Parking": 3.1, "52": 0.9, "70": 0.5, "81": 0.25, "99": 0.0},
}

def dist(a: str, b: str) -> float:
    """Safe distance lookup with a fallback."""
    if a in DIST_KM and b in DIST_KM[a]:
        return float(DIST_KM[a][b])
    # Fallback if missing in matrix (keeps demo alive)
    return 2.5

# =========================================================
# Data (Routes + Zones)
# =========================================================
INITIAL_ROUTES = [
    {
        "truckId": 1,
        "nodeSequence": [DEPOT_NAME, "61", "31", "12", "18", DEPOT_NAME],
        "status": "Pending",
    },
    {
        "truckId": 2,
        "nodeSequence": [DEPOT_NAME, "22", "35", "44", DEPOT_NAME],
        "status": "Pending",
    },
    {
        "truckId": 3,
        "nodeSequence": [DEPOT_NAME, "52", "70", "81", "99", DEPOT_NAME],
        "status": "Pending",
    },
]

# Each zone must have:
# id (unique), truckId, zone (name), binId, fillLevelPercent, estimatedWeightKg, status
INITIAL_ZONES = [
    # Truck 1
    {"id": 101, "truckId": 1, "zone": "Zone A1", "binId": 61, "fillLevelPercent": 80, "estimatedWeightKg": 900.0, "status": "Pending"},
    {"id": 102, "truckId": 1, "zone": "Zone A2", "binId": 31, "fillLevelPercent": 60, "estimatedWeightKg": 800.0, "status": "Pending"},
    {"id": 103, "truckId": 1, "zone": "Zone B1", "binId": 12, "fillLevelPercent": 75, "estimatedWeightKg": 1000.0, "status": "Pending"},
    {"id": 104, "truckId": 1, "zone": "Zone B2", "binId": 18, "fillLevelPercent": 50, "estimatedWeightKg": 700.0, "status": "Pending"},

    # Truck 2
    {"id": 201, "truckId": 2, "zone": "Zone C1", "binId": 22, "fillLevelPercent": 70, "estimatedWeightKg": 950.0, "status": "Pending"},
    {"id": 202, "truckId": 2, "zone": "Zone C2", "binId": 35, "fillLevelPercent": 65, "estimatedWeightKg": 850.0, "status": "Pending"},
    {"id": 203, "truckId": 2, "zone": "Zone D1", "binId": 44, "fillLevelPercent": 55, "estimatedWeightKg": 650.0, "status": "Pending"},

    # Truck 3
    {"id": 301, "truckId": 3, "zone": "Zone D2", "binId": 52, "fillLevelPercent": 85, "estimatedWeightKg": 1100.0, "status": "Pending"},
    {"id": 302, "truckId": 3, "zone": "Zone E1", "binId": 70, "fillLevelPercent": 90, "estimatedWeightKg": 1200.0, "status": "Pending"},
    {"id": 303, "truckId": 3, "zone": "Zone E2", "binId": 81, "fillLevelPercent": 65, "estimatedWeightKg": 800.0, "status": "Pending"},
    {"id": 304, "truckId": 3, "zone": "Zone F1", "binId": 99, "fillLevelPercent": 40, "estimatedWeightKg": 600.0, "status": "Pending"},
]

# Working copies (mutable at runtime)
routes = deepcopy(INITIAL_ROUTES)
zones = deepcopy(INITIAL_ZONES)

# Digital-twin state (server truth)
truck_state: dict[int, dict] = {}

def init_truck_state_if_needed(truck_id: int) -> None:
    """Initialize a truck state if it does not exist yet."""
    if truck_id not in truck_state:
        truck_state[truck_id] = {
            "truckId": truck_id,
            "currentLocation": DEPOT_NAME,
            "cumDistanceKm": 0.0,
            "cumCollectedWeightKg": 0.0,
            "cumEnergyKWh": 0.0,
            "batteryKWh": BATTERY_CAPACITY_KWH,
            "fillRatio": 0.0,
            "efficiencyKWhPerKg": 0.0,
            "rangeLeftKm": (BATTERY_CAPACITY_KWH / ALPHA_KWH_PER_KM) * 0.8,
        }

def get_route_for_truck(truck_id: int):
    for r in routes:
        if int(r.get("truckId")) == int(truck_id):
            return r
    return None

def get_zones_for_truck(truck_id: int):
    return [z for z in zones if int(z.get("truckId")) == int(truck_id)]

def update_route_status(truck_id: int) -> None:
    """Update a route status based on its zones statuses."""
    r = get_route_for_truck(truck_id)
    if not r:
        return
    tz = get_zones_for_truck(truck_id)
    if len(tz) == 0:
        r["status"] = "Pending"
        return
    if all(z["status"] == "Collected" for z in tz):
        r["status"] = "Collected"
    elif any(z["status"] == "Collected" for z in tz):
        r["status"] = "InProgress"
    else:
        r["status"] = "Pending"

def next_pending_zone_for_truck(truck_id: int):
    """
    Find the next pending zone based on the truck route nodeSequence order.
    It matches the first binId in nodeSequence (excluding depot) that is still Pending.
    """
    r = get_route_for_truck(truck_id)
    if not r:
        return None

    seq = r.get("nodeSequence", [])
    ordered_bins: list[int] = []
    for node in seq:
        if node == DEPOT_NAME:
            continue
        try:
            ordered_bins.append(int(node))
        except ValueError:
            pass

    tz = get_zones_for_truck(truck_id)
    for b in ordered_bins:
        for z in tz:
            if int(z.get("binId")) == int(b) and z.get("status") == "Pending":
                return z
    return None

def energy_segment_kwh(distance_km: float, current_load_kg: float) -> float:
    """
    Digital-twin segment energy model (Methodology):
    Energy = Distance * [ alpha + (beta * current_load) ]
    """
    return float(distance_km) * (ALPHA_KWH_PER_KM + BETA_KWH_PER_KG_KM * float(current_load_kg))

def recalc_route_totals(truck_id: int) -> None:
    """
    Recalculate route total distance/energy using current zone statuses:
    - Distance uses the full planned path (depot -> bins -> depot) for demo clarity
    - Energy uses alpha only for route summary (MILP-like), while /truck-state uses simulation model
    """
    r = get_route_for_truck(truck_id)
    if not r:
        return
    seq = r.get("nodeSequence", [])
    total_dist = 0.0
    for i in range(len(seq) - 1):
        total_dist += dist(seq[i], seq[i + 1])

    # Route summary energy (MILP stage): alpha * distance
    total_energy = ALPHA_KWH_PER_KM * total_dist

    # Route weight: sum of all zones for that truck (fixed waste assumption)
    total_weight = sum(float(z.get("estimatedWeightKg", 0.0)) for z in get_zones_for_truck(truck_id))

    r["totalDistanceKm"] = round(total_dist, 2)
    r["totalEnergyKWh"] = round(total_energy, 2)
    r["totalCollectedWeightKg"] = round(total_weight, 2)

def recalc_all_routes() -> None:
    for r in routes:
        tid = int(r["truckId"])
        init_truck_state_if_needed(tid)
        recalc_route_totals(tid)
        update_route_status(tid)

# =========================================================
# Public API
# =========================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"ok": True, "message": "Waste Optimizer backend is running"})

@app.route("/reset", methods=["POST"])
def reset_all():
    """
    Reset all routes/zones/truck_state to the initial Pending state.
    This solves the 'always Collected' problem when the server stays alive on Render.
    """
    global routes, zones, truck_state
    routes = deepcopy(INITIAL_ROUTES)
    zones = deepcopy(INITIAL_ZONES)
    truck_state = {}
    recalc_all_routes()
    return jsonify({"message": "Reset done. All zones/routes are Pending again."})

@app.route("/routes", methods=["GET"])
def get_routes():
    """Return all routes with totals."""
    recalc_all_routes()
    return jsonify(routes)

@app.route("/zones", methods=["GET"])
def get_zones():
    """Return zones. Optional: ?truckId=1"""
    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify(zones)
    return jsonify([z for z in zones if int(z.get("truckId")) == int(truck_id)])

@app.route("/truck-state", methods=["GET"])
def get_truck_state():
    """Return live digital-twin state. Optional: ?truckId=1"""
    recalc_all_routes()
    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify(list(truck_state.values()))
    init_truck_state_if_needed(truck_id)
    return jsonify(truck_state[truck_id])

@app.route("/next-zone", methods=["GET"])
def next_zone():
    """
    Return the next pending zone for a given truck based on route order.
    Query: ?truckId=1
    """
    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify({"error": "truckId is required"}), 400

    recalc_all_routes()
    z = next_pending_zone_for_truck(truck_id)
    return jsonify({"zone": z})

@app.route("/confirm-zone", methods=["POST"])
def confirm_zone():
    """
    Confirm one zone manually and update digital-twin state incrementally.

    Body:
      { "truckId": 1, "zoneId": 101 }

    Rules:
    - Zone must belong to truck
    - Zone must be the next pending zone in route order
    - Apply energy consumption for the segment using load-dependent model
      Energy = Distance * [alpha + beta * current_load]
    - Decrease battery, then collect waste, update load and KPIs
    """
    data = request.get_json(silent=True) or {}
    truck_id = data.get("truckId", None)
    zone_id = data.get("zoneId", None)

    if truck_id is None or zone_id is None:
        return jsonify({"error": "truckId and zoneId are required"}), 400

    truck_id = int(truck_id)
    zone_id = int(zone_id)

    recalc_all_routes()
    init_truck_state_if_needed(truck_id)

    r = get_route_for_truck(truck_id)
    if not r:
        return jsonify({"error": "Route not found for this truckId"}), 404

    # Find zone
    z = next((x for x in zones if int(x.get("id")) == zone_id), None)
    if not z:
        return jsonify({"error": "Zone not found"}), 404

    # Ownership
    if int(z.get("truckId")) != truck_id:
        return jsonify({"error": "Zone does not belong to this truckId"}), 400

    # Status check
    if z.get("status") != "Pending":
        return jsonify({"error": "Zone is not Pending"}), 400

    # Must be next in order
    expected = next_pending_zone_for_truck(truck_id)
    if not expected:
        return jsonify({"error": "No pending zones left for this truck"}), 400
    if int(expected.get("id")) != zone_id:
        return jsonify({
            "error": "This is not the next pending zone in route order",
            "expectedNextZoneId": expected.get("id"),
            "expectedNextBinId": expected.get("binId"),
        }), 400

    state = truck_state[truck_id]

    # Travel segment: current location -> this bin
    current_loc = str(state["currentLocation"])
    next_loc = str(z["binId"])
    d_km = dist(current_loc, next_loc)

    # Energy BEFORE arriving (depends on current load)
    current_load = float(state["cumCollectedWeightKg"])
    e_kwh = energy_segment_kwh(d_km, current_load)

    # Battery safety check
    if float(state["batteryKWh"]) - e_kwh < MIN_BATTERY_KWH:
        return jsonify({
            "error": "Battery would drop below MIN_BATTERY after this move",
            "batteryKWh": state["batteryKWh"],
            "neededEnergyKWh": round(e_kwh, 4),
            "minBatteryKWh": MIN_BATTERY_KWH,
        }), 400

    # Update movement KPIs
    state["cumDistanceKm"] = float(state["cumDistanceKm"]) + d_km
    state["cumEnergyKWh"] = float(state["cumEnergyKWh"]) + e_kwh
    state["batteryKWh"] = float(state["batteryKWh"]) - e_kwh
    state["currentLocation"] = next_loc

    # Collect waste AFTER servicing
    collected_w = float(z.get("estimatedWeightKg", 0.0))
    new_load = float(state["cumCollectedWeightKg"]) + collected_w

    if new_load > MAX_LOAD_KG:
        return jsonify({
            "error": "Capacity exceeded after collecting this zone",
            "cumCollectedWeightKg": new_load,
            "maxLoadKg": MAX_LOAD_KG,
        }), 400

    state["cumCollectedWeightKg"] = new_load

    # Update instantaneous KPIs
    state["fillRatio"] = new_load / MAX_LOAD_KG if MAX_LOAD_KG > 0 else 0.0
    denom = max(new_load, 1.0)
    state["efficiencyKWhPerKg"] = float(state["cumEnergyKWh"]) / denom
    state["rangeLeftKm"] = (float(state["batteryKWh"]) / ALPHA_KWH_PER_KM) * 0.8

    # Mark zone collected and refresh route status
    z["status"] = "Collected"
    update_route_status(truck_id)

    return jsonify({
        "message": "Zone confirmed and digital-twin updated",
        "truckState": state,
        "zone": z,
        "route": get_route_for_truck(truck_id),
        "segment": {"from": current_loc, "to": next_loc, "distanceKm": d_km, "energyKWh": round(e_kwh, 4)},
    })

@app.route("/simulate", methods=["GET"])
def simulate_summary():
    """
    Simple summary endpoint (for your Desktop Dashboard button).
    Returns totals based on digital-twin states (simulation layer).
    """
    recalc_all_routes()

    total_bins = len(zones)
    total_trucks = len(routes)

    # "After" = sum of actual simulated energy so far (digital twin)
    after_energy = sum(float(s["cumEnergyKWh"]) for s in truck_state.values()) if truck_state else 0.0

    # "Before" = baseline using alpha only on full planned route distances (MILP-like)
    before_energy = 0.0
    for r in routes:
        before_energy += float(r.get("totalEnergyKWh", 0.0))

    saving = 0.0
    if before_energy > 0:
        saving = ((before_energy - after_energy) / before_energy) * 100.0

    return jsonify({
        "totalBins": total_bins,
        "totalTrucks": total_trucks,
        "energyBeforeKWh": round(before_energy, 3),
        "energyAfterKWh": round(after_energy, 3),
        "savingPercent": round(saving, 2),
    })

# IMPORTANT:
# I removed /confirm-route on purpose to prevent "always Collected".
# If you still want a demo button to collect all, add it back later carefully.

if __name__ == "__main__":
    # Local run
    app.run(host="0.0.0.0", port=5000, debug=True)
