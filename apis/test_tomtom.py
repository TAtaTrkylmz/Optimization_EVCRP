import requests

# --- CONFIGURATION ---
# Replace this with your actual TomTom API key
TOMTOM_API_KEY = "ORsYLnG0yuFUlpCKURu5Urmhdwcefxsk"

def test_tomtom_geocoding(address):
    """
    Tests the TomTom Geocoding API by searching for an address.
    """
    print(f"Testing TomTom Search API for address: '{address}'...\n")
    
    # TomTom Geocoding API endpoint
    # Reference: https://developer.tomtom.com/search-api/documentation/geocoding-service/geocode
    url = f"https://api.tomtom.com/search/2/geocode/{address}.json"
    
    params = {
        'key': TOMTOM_API_KEY,
        'limit': 1  # We only want the top result
    }
    
    try:
        response = requests.get(url, params=params)
        
        # Check if the request was successful
        if response.status_code == 200:
            data = response.json()
            
            # Check if there are results
            if data.get('results') and len(data['results']) > 0:
                result = data['results'][0]
                position = result.get('position', {})
                address_info = result.get('address', {})
                
                print("✅ API Request Successful!\n")
                print("--- Retrieved Data ---")
                print(f"Formatted Address: {address_info.get('freeformAddress')}")
                print(f"Country: {address_info.get('country')}")
                print(f"Latitude: {position.get('lat')}")
                print(f"Longitude: {position.get('lon')}")
                print("----------------------\n")
            else:
                print("⚠️ API returned a successful response, but no results were found for the given address.")
                print(data)
                
        elif response.status_code in [403, 401]:
            print(f"❌ Error {response.status_code}: Unauthorized. Please check if your API key is valid.")
            print("Response:", response.text)
        else:
            print(f"❌ Error: API request failed with status code {response.status_code}.")
            print("Response:", response.text)
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
        
    print("\n--------------------------------------------------\n")
        
def test_tomtom_routing(start_coords, end_coords):
    """
    Tests the TomTom Routing API by getting a route between two coordinates.
    Format for coords: 'latitude,longitude'
    """
    print(f"Testing TomTom Routing API from '{start_coords}' to '{end_coords}'...\n")
    
    # TomTom Routing API endpoint
    # Format: .../calculateRoute/start_lat,start_lon:end_lat,end_lon/json
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{start_coords}:{end_coords}/json"
    
    params = {
        'key': TOMTOM_API_KEY,
        'routeRepresentation': 'summaryOnly' # Minimal data for testing
    }
    
    try:
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('routes') and len(data['routes']) > 0:
                summary = data['routes'][0].get('summary', {})
                
                print("✅ Routing API Request Successful!\n")
                print("--- Retrieved Route Summary ---")
                # Length is in meters, convert to km
                length_km = summary.get('lengthInMeters', 0) / 1000.0
                # Time is in seconds, convert to minutes
                travel_time_min = summary.get('travelTimeInSeconds', 0) / 60.0
                
                print(f"Distance: {length_km:.2f} km")
                print(f"Estimated Travel Time: {travel_time_min:.2f} minutes")
                print("-------------------------------\n")
            else:
                print("⚠️ API returned a successful response, but no route was found.")
                print(data)
                
        elif response.status_code in [403, 401]:
            print(f"❌ Error {response.status_code}: Unauthorized. Please check your API key.")
            print("Response:", response.text)
        else:
            print(f"❌ Error: API request failed with status code {response.status_code}.")
            print("Response:", response.text)
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")

if __name__ == "__main__":
    if TOMTOM_API_KEY == "YOUR_TOMTOM_API_KEY_HERE":
        print("⚠️ Please open this file and replace 'YOUR_TOMTOM_API_KEY_HERE' with your actual TomTom API key before running.")
    else:
        # 1. Test Geocoding API (using Turkey since the project uses Turkish data)
        test_address = "Kızılay, Ankara, Turkey"
        test_tomtom_geocoding(test_address)
        
        # 2. Test Routing API (Ankara start to a sample destination)
        # Using format: latitude,longitude
        test_start = "39.92077,32.85411"  # Ankara
        test_end = "41.0082,28.9784"      # Istanbul
        test_tomtom_routing(test_start, test_end)
