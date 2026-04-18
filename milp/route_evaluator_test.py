"""
Simple Z-score evaluator test with mock data.

This is a standalone test file demonstrating the Z-score objective
function with different driver profiles. Not part of the main planner.

Run:  python milp/route_evaluator_test.py
"""


def calculate_anxiety_penalty(soc_history, threshold=20):
    """Sum of squared penalties for SOC values below threshold."""
    penalty = 0
    for soc in soc_history:
        if soc < threshold:
            penalty += (threshold - soc) ** 2
    return penalty


def calculate_z_score(travel_time, charging_cost, soc_history,
                      w_time=0.4, w_cost=0.3, w_anxiety=0.3):
    """Weighted Z-score: lower is better."""
    anxiety = calculate_anxiety_penalty(soc_history)
    return w_time * travel_time + w_cost * charging_cost + w_anxiety * anxiety


# ── Test data ──

MOCK_ROUTES = {
    "Route A (Fast & Expensive)": {
        "travel_time": 400,
        "charging_cost": 1500,
        "soc_history": [100, 70, 80, 40, 30],
    },
    "Route B (Slow & Cheap)": {
        "travel_time": 550,
        "charging_cost": 600,
        "soc_history": [100, 50, 40, 15, 60],
    },
    "Route C (The Risky Shortcut)": {
        "travel_time": 380,
        "charging_cost": 500,
        "soc_history": [100, 40, 2],
    },
}

DRIVER_PROFILES = {
    "Rich & Impatient":    {"w_time": 0.8, "w_cost": 0.1, "w_anxiety": 0.1},
    "Budget Student":      {"w_time": 0.2, "w_cost": 0.7, "w_anxiety": 0.1},
    "Extremely Anxious":   {"w_time": 0.2, "w_cost": 0.1, "w_anxiety": 0.7},
}


def main():
    print("--- Z-SCORE EVALUATOR TEST ---\n")

    for profile_name, weights in DRIVER_PROFILES.items():
        print(f"Profile: {profile_name}")
        print(f"  Weights -> time={weights['w_time']}, "
              f"cost={weights['w_cost']}, anxiety={weights['w_anxiety']}")

        best_route, lowest_z = None, float("inf")

        for route_name, data in MOCK_ROUTES.items():
            z = calculate_z_score(
                data["travel_time"], data["charging_cost"],
                data["soc_history"], **weights,
            )
            print(f"  - {route_name}: Z = {z:.2f}")
            if z < lowest_z:
                lowest_z = z
                best_route = route_name

        print(f"  WINNER: {best_route}\n" + "-" * 40 + "\n")


if __name__ == "__main__":
    main()
