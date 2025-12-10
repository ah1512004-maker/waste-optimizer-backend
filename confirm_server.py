from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # allow requests from any origin (localhost:5500, mobile, ...)

# ----- Mock data for routes and zones (same idea as desktop app) -----

routes = [
    {
        "truckId": 1,
        "nodeSequence": ["Parking", "61", "31", "12", "18", "Parking"],
        "totalDistanceKm": 18.4,
        "totalEnergyKWh": 20.2,
        "totalCollectedWeightKg": 140.0,
        "status": "Pending",
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

# zones per bin (you can adjust values later from the article)
zones = [
    # Truck 1
    {"truckId": 1, "zone": "Zone A1", "binId": 61, "fillLevelPercent": 80, "status": "Pending"},
    {"truckId": 1, "zone": "Zone A2", "binId": 31, "fillLevelPercent": 60, "status": "Pending"},
    {"truckId": 1, "zone": "Zone B1", "binId": 12, "fillLevelPercent": 75, "status": "Pending"},
    {"truckId": 1, "zone": "Zone B2", "binId": 18, "fillLevelPercent": 50, "status": "Pending"},

    # Truck 2
    {"truckId": 2, "zone": "Zone C1", "binId": 22, "fillLevelPercent": 70, "status": "Pending"},
    {"truckId": 2, "zone": "Zone C2", "binId": 35, "fillLevelPercent": 65, "status": "Pending"},
    {"truckId": 2, "zone": "Zone D1", "binId": 44, "fillLevelPercent": 55, "status": "Pending"},

    # Truck 3
    {"truckId": 3, "zone": "Zone D2", "binId": 52, "fillLevelPercent": 85, "status": "Pending"},
    {"truckId": 3, "zone": "Zone E1", "binId": 70, "fillLevelPercent": 90, "status": "Pending"},
    {"truckId": 3, "zone": "Zone E2", "binId": 81, "fillLevelPercent": 65, "status": "Pending"},
    {"truckId": 3, "zone": "Zone F1", "binId": 99, "fillLevelPercent": 40, "status": "Pending"},
]


@app.route("/")
def index():
    return jsonify({"message": "Confirm server is running"})


@app.route("/routes", methods=["GET"])
def get_routes():
    """Return all routes for drivers page."""
    return jsonify(routes)


@app.route("/zones", methods=["GET"])
def get_zones():
    zones = [
        {
            "id": 101,
            "truckId": 1,
            "zoneName": "Zone A",
            "fillLevelPercent": 72,
            "status": "Pending"
        },
        {
            "id": 102,
            "truckId": 1,
            "zoneName": "Zone B",
            "fillLevelPercent": 55,
            "status": "Pending"
        },
        {
            "id": 201,
            "truckId": 2,
            "zoneName": "Zone C",
            "fillLevelPercent": 80,
            "status": "Collected"
        }
    ]

    return jsonify(zones)



@app.route("/confirm-route", methods=["POST"])
def confirm_route():
    """Mark route as collected and update its zones."""
    data = request.get_json(silent=True) or {}
    truck_id = data.get("truckId")

    if truck_id is None:
        return jsonify({"status": "error", "message": "truckId is required"}), 400

    # update route status
    for r in routes:
        if r["truckId"] == truck_id:
            r["status"] = "Collected"

    # update zones status
    for z in zones:
        if z["truckId"] == truck_id:
            z["status"] = "Collected"

    return jsonify({"status": "ok", "message": "Route confirmed successfully"})


# Render / gunicorn entrypoint
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
