import random

"""
Mock data generator file

#TODO: LATER we will add weather, traffic and such here also.

"""
def get_mock_station_occupancy(station_id: str, arrival_time_min: float) -> dict:
    """
    Mock data generator for charging station status.
    Provides mocked wait times based on a simulated occupancy level.
    
    """
    # Seed based on station id to have some consistency, but optionally time dependent
    # In a real scenario, this would call an external API.
    # We use a mix of station_id hash and time of day (in 10 min buckets) to simulate time-varying occupancy
    bucket = int(arrival_time_min // 10)
    rng = random.Random(hash(station_id) + bucket)
    
    occupancy_rate = rng.uniform(0.0, 1.0)
    
    wait_time_min = 0.0
    if occupancy_rate > 0.8:
        # High occupancy, 5 to 20 minutes wait
        wait_time_min = rng.uniform(5.0, 20.0)
    elif occupancy_rate > 0.6:
        # Moderate occupancy, 0 to 10 minutes wait
        wait_time_min = rng.uniform(0.0, 10.0)
        
    return {
        "station_id": station_id,
        "occupancy_rate": occupancy_rate,
        "wait_time_min": round(wait_time_min, 1)
    }
