import pulp

# --- 1. MOCK DATA SETUP ---
# Nodes: 0 is Start, 3 is Destination, 1 and 2 are Charging Stations
nodes = [0, 1, 2, 3]

# Edges: (from_node, to_node) -> (travel_time, energy_consumed)
# Example: from 0 to 1 takes 60 mins and 25% battery.
edges = {
    (0, 1): (60, 25),
    (0, 2): (90, 40),
    (1, 2): (30, 10),
    (1, 3): (120, 60),
    (2, 3): (50, 20)
}

# Node Data: (charging_cost_per_unit, charging_time_per_unit)
# Node 0 and 3 have 0 cost/time because you don't charge while driving.
node_data = {
    0: (0.0, 0.0),
    1: (15.0, 2.0), # 15 TL per %, 2 mins per %
    2: (8.0, 5.0),  # 8 TL per %, 5 mins per % (Cheaper but slower)
    3: (0.0, 0.0)
}

B_max = 100       # Maximum Battery Capacity (%)
Threshold = 30    # Anxiety Threshold (%)
w1, w2, w3 = 0.5, 0.2, 0.3 # Weights for Time, Cost, Anxiety

# --- 2. MODEL DEFINITION ---
# Create a Minimization Problem
prob = pulp.LpProblem("EV_Routing_Optimization", pulp.LpMinimize)

# --- 3. DECISION VARIABLES ---
# x_ij: 1 if we travel from node i to node j, else 0 (Binary/Integer)
x = pulp.LpVariable.dicts("x", edges.keys(), cat='Binary')

# q_i: Amount of energy charged at node i (Continuous)
q = pulp.LpVariable.dicts("q", nodes, lowBound=0, cat='Continuous')

# y_i: Battery level upon ARRIVING at node i (Continuous)
y = pulp.LpVariable.dicts("y", nodes, lowBound=0, upBound=B_max, cat='Continuous')

# p_i: Anxiety penalty at node i (Continuous)
p = pulp.LpVariable.dicts("p", nodes, lowBound=0, cat='Continuous')

# --- 4. OBJECTIVE FUNCTION ---
# Minimize Z = w1*(Driving Time + Charging Time) + w2*(Charging Cost) + w3*(Anxiety Penalties)
prob += (
    w1 * pulp.lpSum(x[i, j] * edges[i, j][0] for i, j in edges) +  # Total Driving Time
    w1 * pulp.lpSum(q[i] * node_data[i][1] for i in nodes) +       # Total Charging Time
    w2 * pulp.lpSum(q[i] * node_data[i][0] for i in nodes) +       # Total Charging Cost
    w3 * pulp.lpSum(p[i] for i in nodes)                           # Total Anxiety Penalty
), "Total_Z_Score"


# --- 5. CONSTRAINTS ---

# Constraint A: Flow Conservation (Start at 0, End at 3)
# Leave start node exactly once
prob += pulp.lpSum(x[0, j] for j in nodes if (0, j) in edges) == 1
# Arrive at destination exactly once
prob += pulp.lpSum(x[i, 3] for i in nodes if (i, 3) in edges) == 1

# For intermediate stations (1 and 2), if you enter, you must leave
for k in [1, 2]:
    prob += pulp.lpSum(x[i, k] for i in nodes if (i, k) in edges) == \
            pulp.lpSum(x[k, j] for j in nodes if (k, j) in edges)

# Constraint B: Battery Level Tracking (Big-M formulation)
# If x_ij = 1, then y_j <= y_i + q_i - energy_consumed
M = 200 # A sufficiently large number
prob += y[0] == 100 # Start with 100% battery

for i, j in edges:
    prob += y[j] <= y[i] + q[i] - edges[i, j][1] + M * (1 - x[i, j])
    
# Constraint C: Cannot charge beyond max capacity
for i in nodes:
    prob += y[i] + q[i] <= B_max

# Constraint D: Linearized Anxiety Penalty
# Penalty p_i must be >= (Threshold - y_i). If y_i is high, p_i is pushed to 0.
for i in nodes:
    prob += p[i] >= Threshold - y[i]

# --- 6. SOLVE AND PRINT ---
prob.solve()

print(f"Status: {pulp.LpStatus[prob.status]}")
print(f"Optimized Z-Score: {pulp.value(prob.objective)}")

print("\n--- Route Taken ---")
for i, j in edges:
    if pulp.value(x[i, j]) == 1:
        print(f"Drive from Node {i} to Node {j}")

print("\n--- Charging Strategy ---")
for i in nodes:
    if pulp.value(q[i]) > 0:
        print(f"Charge {pulp.value(q[i])}% at Node {i} (Arrived with {pulp.value(y[i])}%)")