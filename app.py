from flask import Flask, render_template, request, jsonify
import requests
import json
import math
import os
import time

app = Flask(__name__)

# IMPORTANT: Use your OpenRouteService key here. The LocationIQ key is now only for geocoding.
ORS_API_KEY = 'eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjljNTZhMTIzMzk3ZjQ5NDM5N2ZjODBhZmQ4YjUzNDgzIiwiaCI6Im11cm11cjY0In0='
LOCATIONIQ_API_KEY = 'pk.3a7b0d8cd86a661cb6fb6125f7c31483' # Keep your LocationIQ key for geocoding/autocomplete

ACTIVE_BUSES_FILE = 'active_buses.json'

# --- HELPER FUNCTIONS ---

def geocode_stop(stop_name):
    """Converts a stop name to coordinates using LocationIQ."""
    url = f"https://us1.locationiq.com/v1/search.php?key={LOCATIONIQ_API_KEY}&q={stop_name}&format=json&limit=1"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()[0]
        return (float(data['lat']), float(data['lon']))
    except:
        return None

def find_nearest_stop(user_location, stops_on_route):
    """Finds the nearest bus stop to the user by straight-line distance."""
    min_dist = float('inf')
    nearest_stop_name = None
    for stop_name, stop_coords_list in stops_on_route.items():
        stop_coords = tuple(stop_coords_list)
        dist = math.sqrt((user_location[0] - stop_coords[0])**2 + (user_location[1] - stop_coords[1])**2)
        if dist < min_dist:
            min_dist = dist
            nearest_stop_name = stop_name
    return nearest_stop_name, tuple(stops_on_route[nearest_stop_name])

def get_eta(start_coords, end_coords):
    """Gets ETA in minutes from OpenRouteService Directions API."""
    start_lon, start_lat = start_coords[1], start_coords[0]
    end_lon, end_lat = end_coords[1], end_coords[0]
    
    url = "https://api.openrouteservice.org/v2/directions/driving-car"
    headers = {
        'Authorization': ORS_API_KEY,
        'Content-Type': 'application/json'
    }
    body = {
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]]
    }

    try:
        response = requests.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if 'routes' in data and len(data['routes']) > 0:
            duration_seconds = data['routes'][0]['summary']['duration']
            return math.ceil(duration_seconds / 60)
        else:
            print("!!! ORS ETA WARNING: No routes found in API response.")
            return None
            
    except Exception as e:
        print("\n" + "="*20)
        print("!!! ORS ETA CALCULATION FAILED !!!")
        print(f"Specific Error: {e}")
        print("="*20 + "\n")
        return None

# --- HTML PAGE ROUTES ---

@app.route('/')
def home():
    """Serves the new homepage."""
    return render_template('home.html')

@app.route('/passenger')
def passenger_page():
    """Serves the main passenger page."""
    return render_template('passenger.html') # Points to the renamed file

@app.route('/driver')
def driver_panel():
    """Serves the driver's control panel."""
    return render_template('driver.html')

# --- API ENDPOINTS ---

@app.route('/api/autocomplete')
def autocomplete():
    """Handles autocomplete suggestions from LocationIQ."""
    query = request.args.get('q')
    if not query:
        return jsonify([])
    url = f"https://api.locationiq.com/v1/autocomplete.php?key={LOCATIONIQ_API_KEY}&q={query}&limit=5"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        print(f"Autocomplete API error: {e}")
        return jsonify([])

@app.route('/api/create_route', methods=['POST'])
def create_route():
    data = request.json
    route_name = data.get('routeName')
    stop_names = data.get('stops', [])
    stops = {}
    for name in stop_names:
        coords = geocode_stop(name)
        if coords:
            stops[name] = coords
    if len(stops) < 2:
        return jsonify({"success": False, "message": "Need at least 2 valid stops."})
    with open(f"{route_name}.json", 'w') as f:
        json.dump({"stops": stops}, f, indent=4)
    return jsonify({"success": True, "message": f"Route '{route_name}' saved!"})

@app.route('/api/update_location', methods=['POST'])
def update_location():
    data = request.json
    bus_id = data.get('busId')
    if not bus_id:
        return jsonify({"success": False, "message": "Bus ID is required."})
    try:
        with open(ACTIVE_BUSES_FILE, 'r') as f:
            active_buses = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        active_buses = {}
    data['timestamp'] = time.time()
    active_buses[bus_id] = data
    with open(ACTIVE_BUSES_FILE, 'w') as f:
        json.dump(active_buses, f)
    return jsonify({"success": True})

@app.route('/api/active_routes')
def active_routes():
    try:
        with open(ACTIVE_BUSES_FILE, 'r') as f:
            active_buses = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify([])
    current_time = time.time()
    active_routes = set()
    for bus_id, bus_data in list(active_buses.items()):
        if (current_time - bus_data.get('timestamp', 0)) < 120:
             active_routes.add(bus_data.get('route'))
    return jsonify(list(active_routes))

@app.route('/api/get_route_data')
def get_route_data():
    route_name = request.args.get('routeName')
    if not route_name:
        return jsonify({"error": "Route name is required."}), 400
    try:
        with open(f"{route_name}.json", 'r') as f:
            route_data = json.load(f)
        return jsonify(route_data)
    except FileNotFoundError:
        return jsonify({"error": "Route data not found."}), 404

@app.route('/api/bus_status')
def bus_status():
    user_lat = request.args.get('lat', type=float)
    user_lon = request.args.get('lon', type=float)
    route_name = request.args.get('routeName')
    if not all([user_lat, user_lon, route_name]):
        return jsonify({"error": "User location and route name are required."}), 400
    try:
        with open(ACTIVE_BUSES_FILE, 'r') as f:
            all_buses = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"status": "No active buses found."})
    buses_on_route = {bus_id: data for bus_id, data in all_buses.items() if data.get('route') == route_name}
    if not buses_on_route:
        return jsonify({"status": f"No active buses found for {route_name}."})
    try:
        with open(f"{route_name}.json", 'r') as f:
            route_data = json.load(f)
    except FileNotFoundError:
        return jsonify({"error": f"Route data for '{route_name}' not found."})

    user_location = (user_lat, user_lon)
    stops_on_route = route_data['stops']
    nearest_stop_name, nearest_stop_coords = find_nearest_stop(user_location, stops_on_route)

    closest_bus = None
    min_eta = float('inf')
    for bus_id, bus_data in buses_on_route.items():
        eta = get_eta(bus_data['location'], nearest_stop_coords)
        if eta is not None and eta < min_eta:
            min_eta = eta
            closest_bus = {
                "busId": bus_id,
                "busLocation": bus_data['location'],
                "routeName": route_name,
                "nearestStop": {"name": nearest_stop_name, "coords": nearest_stop_coords},
                "eta": min_eta
            }
    if closest_bus:
        return jsonify({"status": "Bus is active.", **closest_bus})
    else:
        return jsonify({"status": f"Could not calculate ETA for buses on {route_name}."})

# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')