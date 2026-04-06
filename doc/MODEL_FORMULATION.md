# EV Charging Route Problem — Model Formulation

## Problem

Given a source, a destination, a set of charging stations along the corridor,
and user preferences, find the route and charging plan that minimises a weighted
objective combining travel time, charging cost, and range-anxiety penalty.

---

## Sets

| Symbol | Description |
|--------|-------------|
| N = {0, 1, …, n−1} | Ordered node set.  Node 0 = origin, node n−1 = destination, all others are candidate charging stations (sorted by along-track parameter *t*). |
| E ⊆ N × N | Directed forward edges.  (i, j) ∈ E iff i < j and the energy requirement e_ij ≤ B_max. |

---

## Parameters (Input Data / Constants)

| Symbol | Unit | Description |
|--------|------|-------------|
| B_max | % | Maximum battery capacity (100 %) |
| B_start | % | User-specified initial battery level |
| B_end | % | User-specified minimum battery level at destination |
| B_floor | % | User-specified minimum battery level **during** travel (enroute floor) |
| B_ceil | % | User-specified maximum battery level **during** travel (enroute ceiling, limits charging) |
| τ (tau) | % | Anxiety threshold — penalty activates below this SOC |
| e_ij | % | Energy consumed travelling edge (i → j), calculated as: `(d_ij × R / 100) × (1 / C_bat) × 100 × F_ext`  where d_ij = road-adjusted distance (km), R = consumption (kWh/100 km), C_bat = battery capacity (kWh) |
| t_ij | min | Travel time on edge (i → j), scaled proportionally from TomTom route summary |
| c_q | TL/% | Flat charging cost per percent charged |
| P_i | kW | Maximum charger power at station i |
| η | — | DC charging efficiency (0.88) |
| F_ext | — | External factor multiplier on energy consumption (weather, terrain, wind, temperature).  Default = 1.0 |
| w_1, w_2, w_3 | — | User-preference weights for time, cost, anxiety.  Each ∈ [0.2, 1.0], computed as priority / 5 |

---

## Decision Variables

| Symbol | Domain | Description |
|--------|--------|-------------|
| x_ij | {0, 1} | 1 if edge (i → j) is used in the route, 0 otherwise |
| q_i | ℝ ≥ 0 | Amount of energy (%) charged at node i |
| y_i | [0, B_max] | Battery state-of-charge (%) on **arrival** at node i |
| p_i | ℝ ≥ 0 | Anxiety penalty at node i |

---

## Objective Function

Minimise:

```
Z = w₁ · ( Σ_{(i,j)∈E} x_ij · t_ij  +  Σ_{i∈N} q_i · r_i )
  + w₂ · ( Σ_{i∈N} q_i · c_q )
  + w₃ · ( Σ_{i∈N} p_i )
```

where r_i is the charging time per percent at station i:

```
r_i = (C_bat / 100) / (P_i · η) × 60     [min / %]
```

The three terms are:

| Term | Controlled by | Represents |
|------|---------------|------------|
| w₁ · (drive time + charge time) | priority_time | Total trip duration |
| w₂ · (charge cost) | priority_cost | Total monetary cost |
| w₃ · (anxiety penalty) | priority_anxiety | Discomfort from low SOC |

---

## Constraints

### 1.  Flow Conservation

```
Σ_j  x_{0,j}  = 1                             (leave origin exactly once)
Σ_i  x_{i,n-1} = 1                             (arrive at destination exactly once)
∀ k ∈ N \ {0, n-1}:  Σ_i x_{ik} = Σ_j x_{kj}  (if you enter, you must leave)
```

### 2.  Battery Tracking (Big-M)

```
∀ (i,j) ∈ E:   y_j ≤ y_i + q_i − e_ij + M·(1 − x_ij)
```

When x_ij = 1, this becomes  y_j ≤ y_i + q_i − e_ij  (battery balance).
When x_ij = 0, the constraint is relaxed by the big-M constant.

### 3.  Initial Battery

```
y_0 = B_start
```

### 4.  Terminal Battery

```
y_{n-1} ≥ B_end
```

### 5.  Capacity Limit (Enroute Ceiling)

```
∀ i ∈ N:   y_i + q_i ≤ B_ceil
```

No node's post-charge SOC can exceed the user-specified enroute ceiling.

### 6.  Enroute Floor

```
∀ i ∈ N:   y_i ≥ B_floor
```

Battery on arrival at **every** node must stay at or above the user-specified floor.

### 7.  Anxiety Penalty Linearisation

```
∀ i ∈ N:   p_i ≥ τ − y_i
            p_i ≥ 0
```

If SOC is above the threshold τ, p_i is driven to 0 by the minimiser.
If SOC is below τ, p_i captures the deficit (τ − y_i).

### 8.  No Charging at Origin / Destination

```
q_0 = 0,   q_{n-1} = 0
```

### 9.  External Factor

The external factor F_ext is **not** a constraint — it is a parameter that
**scales all edge energy values** before the optimisation:

```
e_ij  ←  e_ij  ×  F_ext
```

This uniformly increases (F_ext > 1) or decreases (F_ext < 1) the energy
needed for every leg, modelling conditions such as:

| F_ext | Condition |
|-------|-----------|
| 1.0 | Nominal / clear weather |
| 1.10–1.15 | Light rain or mild headwind |
| 1.20–1.30 | Heavy rain, snow, strong headwind, cold weather |
| 1.40+ | Extreme winter / mountain pass |
| 0.90–0.95 | Favourable tailwind, flat terrain |

---

## Summary Table

| Category | Count | Items |
|----------|-------|-------|
| **Sets** | 2 | N (nodes), E (edges) |
| **Parameters** | 12 | B_max, B_start, B_end, B_floor, B_ceil, τ, e_ij, t_ij, c_q, P_i, η, F_ext |
| **User Prefs** | 3 | w₁ (time), w₂ (cost), w₃ (anxiety) |
| **Variables** | 4 | x_ij (binary), q_i (continuous), y_i (continuous), p_i (continuous) |
| **Constraints** | 9 | Flow (3), battery tracking, initial/terminal battery, ceiling, floor, anxiety, no charge at endpoints, external factor scaling |

---

## Solver

The current implementation uses **forward dynamic programming** (NumPy) rather than a MILP solver. The state space is `(node, battery_level)` with battery discretised to 1 % steps and charge amounts in 5 % steps. The DP enforces all the constraints above implicitly by only expanding feasible states.

The legacy MILP formulation in `milp/MILP_solverfw_test.py` and `milp/izmir_ankara_tomtom_epdk_test.py` uses PuLP/CBC with the same mathematical model.
