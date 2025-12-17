from __future__ import annotations

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS


# ------------------------------------------------------------
# Flask app setup
# ------------------------------------------------------------
app = Flask(__name__)
CORS(app)  # Allow requests from any origin (Desktop app, GitHub pages, etc.)


# ------------------------------------------------------------
# Model / parameters (editable)
# ------------------------------------------------------------
ALPHA_KWH_PER_KM = 0.86
# Small weight-energy factor (tunable). If you have the real equation from PDF, adjust this.
BETA_KWH_PER_KG_KM = ALPHA_KWH_PER_KM / 10000.0

MAX_BATTERY_KWH = 100.0
MIN_BATTERY_KWH = 20.0
MAX_LOAD_KG = 5000.0

DEPOT_NAME = "Parking"


# ------------------------------------------------------------
# Demo data (routes + zones)
# IMPORTANT: Keep binIds consistent with route nodeSequence.
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

# Each zone must have a unique integer id for reliable confirmation
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
# Digital Twin state (server-side truth)
# ------------------------------------------------------------
truck_state: dict[int, dict] = {}


def init_truck_state_if_needed(truck_id: int) -> None:
    """Initialize a truck state once (server-side digital twin)."""
    if truck_id not in truck_state:
        truck_state[truck_id] = {
            "truckId": truck_id,
            "currentLocation": DEPOT_NAME,
            "cumDistanceKm": 0.0,
            "cumCollectedWeightKg": 0.0,
            "cumEnergyKWh": 0.0,
            "batteryKWh": float(MAX_BATTERY_KWH),
            "fillRatio": 0.0,
            "efficiencyKWhPerKg": 0.0,
            "rangeLeftKm": (MAX_BATTERY_KWH / ALPHA_KWH_PER_KM) * 0.8,  # safety margin
        }


def get_route_for_truck(truck_id: int) -> dict | None:
    for r in routes:
        if r.get("truckId") == truck_id:
            return r
    return None


def get_zones_for_truck(truck_id: int) -> list[dict]:
    return [z for z in zones if z.get("truckId") == truck_id]


def next_pending_zone_for_truck(truck_id: int) -> dict | None:
    """
    Return the next pending zone based on the route nodeSequence order.
    We take route order, then return the first zone whose status is Pending.
    """
    route = get_route_for_truck(truck_id)
    if not route:
        return None

    ordered_bins: list[int] = []
    for node in route.get("nodeSequence", []):
        if node == DEPOT_NAME:
            continue
        try:
            ordered_bins.append(int(node))
        except ValueError:
            continue

    tz = get_zones_for_truck(truck_id)

    for bin_id in ordered_bins:
        for z in tz:
            if z.get("binId") == bin_id and z.get("status") == "Pending":
                return z

    return None


def calculate_distance_km(current_loc: str, next_bin_id: int) -> float:
    """
    Placeholder distance function.
    Replace with:
      - Dist matrix from your dataset, or
      - Haversine using GPS coords, etc.
    """
    # Simple mock: fixed distance per hop
    return 2.5


def calculate_energy_kwh(distance_km: float, carried_weight_kg: float) -> float:
    """
    Energy model:
      E = alpha * d + beta * d * current_load
    """
    base = ALPHA_KWH_PER_KM * distance_km
    weight_part = BETA_KWH_PER_KG_KM * distance_km * carried_weight_kg
    return base + weight_part


def update_route_status(truck_id: int) -> None:
    """Update route status based on its zones completion."""
    route = get_route_for_truck(truck_id)
    if not route:
        return

    tz = get_zones_for_truck(truck_id)
    if tz and all(z.get("status") == "Collected" for z in tz):
        route["status"] = "Collected"
    elif any(z.get("status") == "Collected" for z in tz):
        route["status"] = "InProgress"
    else:
        route["status"] = "Pending"


def reset_all() -> None:
    """Reset routes, zones, and truck_state to initial values for demo/testing."""
    # Reset zones
    for z in zones:
        z["status"] = "Pending"

    # Reset routes
    for r in routes:
        r["status"] = "Pending"

    # Reset digital twin
    truck_state.clear()


# ------------------------------------------------------------
# API endpoints
# ------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return jsonify({"message": "Waste Optimizer backend is running"})


@app.route("/routes", methods=["GET"])
def get_routes():
    """Return all routes for UI."""
    for r in routes:
        init_truck_state_if_needed(int(r["truckId"]))
    return jsonify(routes)


@app.route("/zones", methods=["GET"])
def get_zones():
    """
    Return all zones.
    Optional query: ?truckId=1
    """
    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify(zones)
    return jsonify([z for z in zones if z.get("truckId") == truck_id])


@app.route("/truck-state", methods=["GET"])
def get_truck_state():
    """
    Return server-side truck digital twin state.
    Optional query: ?truckId=1
    """
    for r in routes:
        init_truck_state_if_needed(int(r["truckId"]))

    truck_id = request.args.get("truckId", type=int)
    if truck_id is None:
        return jsonify(list(truck_state.values()))

    init_truck_state_if_needed(truck_id)
    return jsonify(truck_state[truck_id])


@app.route("/next-zone", methods=["GET"])
def get_next_zone():
    """
    Return the next pending zone for a given truck based on route order.
    Query: /next-zone?truckId=1
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
    Manual confirmation (zone-by-zone).
    Body:
      { "truckId": 1, "zoneId": 101 }

    Rules:
    - Zone must belong to truck
    - Zone must be the NEXT pending zone in the route order
    - Update zone status + digital twin + route status
    """
    data = request.get_json(silent=True) or {}
    truck_id = data.get("truckId")
    zone_id = data.get("zoneId")

    if truck_id is None or zone_id is None:
        return jsonify({"error": "truckId and zoneId are required"}), 400

    try:
        truck_id = int(truck_id)
        zone_id = int(zone_id)
    except Exception:
        return jsonify({"error": "truckId and zoneId must be integers"}), 400

    init_truck_state_if_needed(truck_id)

    route = get_route_for_truck(truck_id)
    if not route:
        return jsonify({"error": "Route not found for this truckId"}), 404

    # Find the requested zone
    zone = next((z for z in zones if int(z.get("id")) == zone_id), None)
    if not zone:
        return jsonify({"error": "Zone not found"}), 404

    # Validate ownership
    if int(zone.get("truckId")) != truck_id:
        return jsonify({"error": "Zone does not belong to this truckId"}), 400

    # Validate status
    if zone.get("status") != "Pending":
        return jsonify({"error": "Zone is not Pending"}), 400

    # Validate it is the next pending zone
    expected = next_pending_zone_for_truck(truck_id)
    if not expected:
        return jsonify({"error": "No pending zones left for this truck"}), 400

    if int(expected.get("id")) != zone_id:
        return jsonify({
            "error": "This is not the next pending zone in the route order",
            "expectedNextZoneId": expected.get("id"),
            "expectedNextBinId": expected.get("binId"),
        }), 400

    # ---- Digital twin update (travel + energy + collect) ----
    state = truck_state[truck_id]

    distance_km = calculate_distance_km(str(state["currentLocation"]), int(zone["binId"]))
    energy_kwh = calculate_energy_kwh(distance_km, float(state["cumCollectedWeightKg"]))

    # Battery safety check
    if float(state["batteryKWh"]) - energy_kwh < float(MIN_BATTERY_KWH):
        return jsonify({
            "error": "Battery would drop below MIN_BATTERY after this move",
            "batteryKWh": state["batteryKWh"],
            "neededEnergyKWh": energy_kwh,
            "minBatteryKWh": MIN_BATTERY_KWH,
        }), 400

    # Move updates
    state["cumDistanceKm"] = float(state["cumDistanceKm"]) + float(distance_km)
    state["cumEnergyKWh"] = float(state["cumEnergyKWh"]) + float(energy_kwh)
    state["batteryKWh"] = float(state["batteryKWh"]) - float(energy_kwh)

    # Collect updates
    collected_weight = float(zone.get("estimatedWeightKg", 0.0))
    state["cumCollectedWeightKg"] = float(state["cumCollectedWeightKg"]) + collected_weight

    # Capacity check
    if float(state["cumCollectedWeightKg"]) > float(MAX_LOAD_KG):
        return jsonify({
            "error": "Capacity exceeded after collecting this zone",
            "cumCollectedWeightKg": state["cumCollectedWeightKg"],
            "maxLoadKg": MAX_LOAD_KG,
        }), 400

    # Update KPIs
    state["fillRatio"] = float(state["cumCollectedWeightKg"]) / float(MAX_LOAD_KG) if MAX_LOAD_KG > 0 else 0.0
    denom = max(float(state["cumCollectedWeightKg"]), 1.0)
    state["efficiencyKWhPerKg"] = float(state["cumEnergyKWh"]) / denom
    state["rangeLeftKm"] = (float(state["batteryKWh"]) / float(ALPHA_KWH_PER_KM)) * 0.8

    # Update current location
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


@app.route("/reset", methods=["POST"])
def reset_endpoint():
    """
    Reset everything to initial Pending state.
    Useful for demos.
    """
    reset_all()
    return jsonify({"message": "Reset done"})


@app.route("/simulate", methods=["POST"])
def simulate():
    """
    OPTIONAL: run an automatic step-by-step simulation on the server.

    Body examples:
      { "reset": true, "maxSteps": 999 }

    Behavior:
    - If reset=true: reset first
    - Then, repeatedly confirm the next zone for each truck (round-robin)
      until maxSteps reached or all zones collected.

    Returns a summary useful for your Desktop Results page.
    """
    data = request.get_json(silent=True) or {}
    do_reset = bool(data.get("reset", False))
    max_steps = int(data.get("maxSteps", 999))

    if do_reset:
        reset_all()

    # Ensure truck states exist
    for r in routes:
        init_truck_state_if_needed(int(r["truckId"]))

    steps = []
    step_count = 0

    # Round-robin across trucks
    truck_ids = [int(r["truckId"]) for r in routes]

    while step_count < max_steps:
        progressed = False

        for tid in truck_ids:
            nz = next_pending_zone_for_truck(tid)
            if not nz:
                continue

            # Internally perform the same logic as confirm-zone (without re-validating next-zone)
            state = truck_state[tid]
            distance_km = calculate_distance_km(str(state["currentLocation"]), int(nz["binId"]))
            energy_kwh = calculate_energy_kwh(distance_km, float(state["cumCollectedWeightKg"]))

            if float(state["batteryKWh"]) - energy_kwh < float(MIN_BATTERY_KWH):
                steps.append({
                    "truckId": tid,
                    "event": "BatteryStop",
                    "batteryKWh": state["batteryKWh"],
                    "neededEnergyKWh": energy_kwh,
                })
                continue

            # Apply move
            state["cumDistanceKm"] = float(state["cumDistanceKm"]) + float(distance_km)
            state["cumEnergyKWh"] = float(state["cumEnergyKWh"]) + float(energy_kwh)
            state["batteryKWh"] = float(state["batteryKWh"]) - float(energy_kwh)

            # Apply collect
            collected_weight = float(nz.get("estimatedWeightKg", 0.0))
            state["cumCollectedWeightKg"] = float(state["cumCollectedWeightKg"]) + collected_weight

            if float(state["cumCollectedWeightKg"]) > float(MAX_LOAD_KG):
                steps.append({
                    "truckId": tid,
                    "event": "CapacityStop",
                    "cumCollectedWeightKg": state["cumCollectedWeightKg"],
                    "maxLoadKg": MAX_LOAD_KG,
                })
                continue

            state["fillRatio"] = float(state["cumCollectedWeightKg"]) / float(MAX_LOAD_KG) if MAX_LOAD_KG > 0 else 0.0
            denom = max(float(state["cumCollectedWeightKg"]), 1.0)
            state["efficiencyKWhPerKg"] = float(state["cumEnergyKWh"]) / denom
            state["rangeLeftKm"] = (float(state["batteryKWh"]) / float(ALPHA_KWH_PER_KM)) * 0.8
            state["currentLocation"] = str(nz["binId"])

            # Mark zone collected
            nz["status"] = "Collected"
            update_route_status(tid)

            steps.append({
                "truckId": tid,
                "zoneId": nz["id"],
                "binId": nz["binId"],
                "distanceKm": distance_km,
                "energyKWh": energy_kwh,
                "batteryKWh": state["batteryKWh"],
                "cumEnergyKWh": state["cumEnergyKWh"],
                "cumDistanceKm": state["cumDistanceKm"],
                "cumCollectedWeightKg": state["cumCollectedWeightKg"],
            })

            step_count += 1
            progressed = True

            if step_count >= max_steps:
                break

        # Stop if nothing progressed (all done or blocked)
        if not progressed:
            break

    # Build summary
    total_energy = sum(float(truck_state[tid]["cumEnergyKWh"]) for tid in truck_state)
    total_distance = sum(float(truck_state[tid]["cumDistanceKm"]) for tid in truck_state)
    collected_all = all(z.get("status") == "Collected" for z in zones)

    return jsonify({
        "message": "Simulation finished",
        "steps": steps,
        "summary": {
            "totalEnergyKWh": total_energy,
            "totalDistanceKm": total_distance,
            "allCollected": collected_all,
        },
        "routes": routes,
        "zones": zones,
        "truckState": list(truck_state.values()),
    })


# ------------------------------------------------------------
# Local dev entrypoint
# ------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
