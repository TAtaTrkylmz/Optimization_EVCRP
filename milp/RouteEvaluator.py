class RouteEvaluator:
    def __init__(self, w1=0.4, w2=0.3, w3=0.3):
        self.w1 = w1
        self.w2 = w2
        self.w3 = w3

    def calculate_anxiety_penalty(self, soc_history, threshold=20):
        penalty = 0
        for soc in soc_history:
            if soc < threshold:
                penalty += (threshold - soc) ** 2
        return penalty

    def calculate_total_z(self, travel_time, charging_cost, soc_history):
        p_penalty = self.calculate_anxiety_penalty(soc_history)
        z_score = (self.w1 * travel_time) + \
                  (self.w2 * charging_cost) + \
                  (self.w3 * p_penalty)
        return z_score

# --- MOCK DATA SETUP ---

# 1. Define the Routes
mock_routes = {
    "Route A (Fast & Expensive)": {
        "travel_time": 400, 
        "charging_cost": 1500, 
        "soc_history": [100, 70, 80, 40, 30] # Safe battery levels
    },
    "Route B (Slow & Cheap)": {
        "travel_time": 550, 
        "charging_cost": 600, 
        "soc_history": [100, 50, 40, 15, 60] # Dips to 15% (minor penalty)
    },
    "Route C (The Risky Shortcut)": {
        "travel_time": 380, 
        "charging_cost": 500, 
        "soc_history": [100, 40, 2] # Dips to 2% (massive penalty!)
    }
}

# 2. Define the Driver Profiles (Weights must sum to 1.0)
driver_profiles = {
    "Rich & Impatient Driver": {"w1": 0.8, "w2": 0.1, "w3": 0.1},
    "Budget Student Driver":   {"w1": 0.2, "w2": 0.7, "w3": 0.1},
    "Extremely Anxious Driver":{"w1": 0.2, "w2": 0.1, "w3": 0.7}
}

# --- RUNNING THE TESTS ---

print("--- EV ROUTING OBJECTIVE FUNCTION TEST ---\n")

for profile_name, weights in driver_profiles.items():
    print(f"Testing Profile: {profile_name}")
    print(f"Weights -> Time: {weights['w1']}, Cost: {weights['w2']}, Anxiety: {weights['w3']}")
    
    # Create an evaluator for this specific driver
    evaluator = RouteEvaluator(w1=weights["w1"], w2=weights["w2"], w3=weights["w3"])
    
    best_route = None
    lowest_z = float('inf') # Start with infinity so the first route always beats it
    
    # Test all routes for this driver
    for route_name, data in mock_routes.items():
        z_score = evaluator.calculate_total_z(
            travel_time=data["travel_time"],
            charging_cost=data["charging_cost"],
            soc_history=data["soc_history"]
        )
        
        print(f"  - {route_name} Z-Score: {z_score:.2f}")
        
        # Check if this is the new best route
        if z_score < lowest_z:
            lowest_z = z_score
            best_route = route_name
            
    print(f"🏆 WINNER for {profile_name}: {best_route} \n" + "-"*40 + "\n")