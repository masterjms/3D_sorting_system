"""
model_3d_sorter_compact.py

Compact MILP model for a 3D Robotized Sorting System with:
- no rack-front buffer,
- direct AMR-shuttle handover,
- one shuttle per rack,
- fixed AMR assignment/sequence,
- fixed rack/shuttle processing sequence by piece index/order,
- no CP reuse,
"""

from __future__ import annotations

from typing import Any

import gurobipy as gp
from gurobipy import GRB


def build_3d_sorter_mip(
    *,
    P: list[int],
    O: list[int],
    G: list[str],
    C: list[int],
    B: list[int],
    C_b: dict[int, list[int]],
    g_p: dict[int, str],
    l_p: dict[int, int],
    d: dict[tuple[int, str], int],
    tau_LB: dict[tuple[int, int], float],
    tau_BL: dict[tuple[int, int], float],
    tau_BC: dict[tuple[int, int], float],
    rho: dict[tuple[int, int], float],
    h: dict[int, float],
    A_b: dict[int, float],
    A_c: dict[int, float],
    S0: dict[int, float],
    K_AMR: list[tuple[int, int]],
    big_m: float = 10000.0,
    time_limit: float = 300.0,
    mip_gap: float = 0.01,
    output_flag: int = 1,
) -> tuple[gp.Model, dict[str, Any]]:
    """
    Build the compact 3D sorter MILP model.

    Required input structure:
    - P: piece set
    - O: order set
    - G: SKU set
    - C: collection point set
    - B: rack/shuttle module set
    - C_b[b]: CPs belonging to rack b
    - g_p[p]: SKU of piece p
    - l_p[p]: loading station of piece p
    - d[o, sku]: demand quantity of SKU sku for order o
    - tau_LB[l, b]: AMR travel time from loading station l to rack b
    - tau_BL[b, l]: AMR return time from rack b to loading station l
    - tau_BC[b, c]: shuttle travel/insert time from rack b to CP c
    - rho[b, c]: shuttle return time after inserting at CP c
    - h[b]: AMR-shuttle handover time at rack b
    - A_b[b]: initial availability time of rack/shuttle b
    - A_c[c]: initial availability time of CP c
    - S0[p]: earliest AMR start time for piece p
    - K_AMR: fixed consecutive piece pairs handled by the same AMR
    """

    # =========================================================
    # 0. Validation and derived mapping
    # =========================================================

    if len(O) > len(C):
        raise ValueError(
            "No CP reuse is allowed. Therefore |O| must be <= |C|. "
            f"Got |O|={len(O)}, |C|={len(C)}."
        )

    cp_seen: list[int] = []
    for b in B:
        if b not in C_b:
            raise ValueError(f"Missing C_b entry for rack {b}.")
        cp_seen.extend(C_b[b])

    if set(cp_seen) != set(C):
        raise ValueError("Every CP must belong to exactly one rack in C_b.")

    if len(cp_seen) != len(set(cp_seen)):
        raise ValueError("A CP appears in more than one rack in C_b.")

    rack_of_cp: dict[int, int] = {}
    for b in B:
        for c in C_b[b]:
            rack_of_cp[c] = b

    # =========================================================
    # 1. Model
    # =========================================================

    model = gp.Model("3D_RSS_NoBuffer_Compact_MIP")
    M = big_m

    # =========================================================
    # 2. Decision variables
    # =========================================================

    # x[p,o] = 1 if piece p is assigned to order o
    x = model.addVars(P, O, vtype=GRB.BINARY, name="x_piece_order")

    # y[o,c] = 1 if order o is assigned to CP c
    y = model.addVars(O, C, vtype=GRB.BINARY, name="y_order_cp")

    # m[p,c] = 1 if piece p is finally inserted into CP c
    # Compact formulation directly links m with x and y; no w[p,o,c] is used.
    m = model.addVars(P, C, vtype=GRB.BINARY, name="m_piece_cp")

    # r[p,b] = 1 if piece p uses rack/shuttle b
    r = model.addVars(P, B, vtype=GRB.BINARY, name="r_piece_rack")

    # Timing variables
    S = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="S_amr_start")
    E = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="E_amr_arrive_rack")
    H = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="H_handover_start")
    Grel = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="G_amr_release")
    Dp = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="D_piece_cp_done")
    F = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="F_shuttle_release")
    Wamr = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="W_amr_wait")

    # Order completion and makespan
    Co = model.addVars(O, lb=0, vtype=GRB.CONTINUOUS, name="C_order")
    Cmax = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="Cmax")

    # =========================================================
    # 3. Objective
    # =========================================================

    model.setObjective(Cmax, GRB.MINIMIZE)

    # =========================================================
    # 4. Constraints
    # =========================================================

    # ---------------------------------------------------------
    # 4.1 Piece-to-Order assignment
    # ---------------------------------------------------------

    for p in P:
        model.addConstr(
            gp.quicksum(x[p, o] for o in O) == 1,
            name=f"one_order_per_piece[{p}]",
        )

    for p in P:
        for o in O:
            if d.get((o, g_p[p]), 0) == 0:
                model.addConstr(
                    x[p, o] == 0,
                    name=f"incompatible_piece_order[{p},{o}]",
                )

    for o in O:
        for sku in G:
            model.addConstr(
                gp.quicksum(x[p, o] for p in P if g_p[p] == sku)
                <= d.get((o, sku), 0),
                name=f"demand_limit[{o},{sku}]",
            )

    # ---------------------------------------------------------
    # 4.2 Order-to-CP assignment
    # ---------------------------------------------------------

    for o in O:
        model.addConstr(
            gp.quicksum(y[o, c] for c in C) == 1,
            name=f"one_cp_per_order[{o}]",
        )

    for c in C:
        model.addConstr(
            gp.quicksum(y[o, c] for o in O) <= 1,
            name=f"one_order_per_cp[{c}]",
        )

    # ---------------------------------------------------------
    # 4.3 Piece-Order-CP linking, compact formulation
    #
    # Original extended formulation:
    #   w[p,o,c] = x[p,o] * y[o,c]
    #   m[p,c]   = sum_o w[p,o,c]
    #
    # Compact formulation used here:
    #   m[p,c] >= x[p,o] + y[o,c] - 1
    #   m[p,c] <= y[o,c] + 1 - x[p,o]
    # ---------------------------------------------------------

    for p in P:
        for o in O:
            for c in C:
                model.addConstr(
                    m[p, c] >= x[p, o] + y[o, c] - 1,
                    name=f"m_ge_x_plus_y_minus_1[{p},{o},{c}]",
                )
                model.addConstr(
                    m[p, c] <= y[o, c] + 1 - x[p, o],
                    name=f"m_le_y_plus_1_minus_x[{p},{o},{c}]",
                )

    for p in P:
        model.addConstr(
            gp.quicksum(m[p, c] for c in C) == 1,
            name=f"one_cp_per_piece[{p}]",
        )

    # ---------------------------------------------------------
    # 4.4 Piece-to-Rack/Shuttle linking
    # ---------------------------------------------------------

    for p in P:
        for b in B:
            model.addConstr(
                r[p, b] == gp.quicksum(m[p, c] for c in C_b[b]),
                name=f"piece_rack_link[{p},{b}]",
            )

    for p in P:
        model.addConstr(
            gp.quicksum(r[p, b] for b in B) == 1,
            name=f"one_rack_per_piece[{p}]",
        )

    # ---------------------------------------------------------
    # 4.5 AMR start and rack arrival time
    # ---------------------------------------------------------

    for p in P:
        model.addConstr(
            S[p] >= S0[p],
            name=f"amr_start_after_piece_available[{p}]",
        )
        model.addConstr(
            E[p] >= S[p] + gp.quicksum(tau_LB[l_p[p], b] * r[p, b] for b in B),
            name=f"amr_arrival_at_rack[{p}]",
        )

    # ---------------------------------------------------------
    # 4.6 No-buffer direct handover constraints
    # ---------------------------------------------------------

    for p in P:
        model.addConstr(
            H[p] >= E[p],
            name=f"handover_after_amr_arrival[{p}]",
        )
        model.addConstr(
            H[p] >= gp.quicksum(A_b[b] * r[p, b] for b in B),
            name=f"handover_after_initial_shuttle_available[{p}]",
        )
        model.addConstr(
            Grel[p] >= H[p] + gp.quicksum(h[b] * r[p, b] for b in B),
            name=f"amr_release_after_handover[{p}]",
        )
        model.addConstr(
            Wamr[p] == H[p] - E[p],
            name=f"amr_waiting_time[{p}]",
        )

    # ---------------------------------------------------------
    # 4.7 Same AMR consecutive job constraints
    # ---------------------------------------------------------

    for p, pp in K_AMR:
        model.addConstr(
            S[pp]
            >= Grel[p] + gp.quicksum(tau_BL[b, l_p[pp]] * r[p, b] for b in B),
            name=f"same_amr_next_job[{p},{pp}]",
        )

    # ---------------------------------------------------------
    # 4.8 CP availability
    # ---------------------------------------------------------

    for p in P:
        model.addConstr(
            Dp[p] >= gp.quicksum(A_c[c] * m[p, c] for c in C),
            name=f"cp_initial_available[{p}]",
        )

    # ---------------------------------------------------------
    # 4.9 Rack/Shuttle processing time
    # ---------------------------------------------------------

    for p in P:
        model.addConstr(
            Dp[p]
            >= H[p]
            + gp.quicksum(
                (h[rack_of_cp[c]] + tau_BC[rack_of_cp[c], c]) * m[p, c]
                for c in C
            ),
            name=f"piece_cp_completion[{p}]",
        )
        model.addConstr(
            F[p]
            >= H[p]
            + gp.quicksum(
                (
                    h[rack_of_cp[c]]
                    + tau_BC[rack_of_cp[c], c]
                    + rho[rack_of_cp[c], c]
                )
                * m[p, c]
                for c in C
            ),
            name=f"shuttle_release[{p}]",
        )

    # ---------------------------------------------------------
    # 4.10 Rack/Shuttle single-processing sequencing
    #
    # Fixed-sequence version:
    # - q[p,p',b] is removed.
    # - If p < p' and both pieces use the same rack b,
    #   piece p must be completed by the shuttle before piece p'
    #   starts handover.
    # ---------------------------------------------------------

    for p in P:
        for pp in P:
            if p < pp:
                for b in B:
                    model.addConstr(
                        H[pp]
                        >= F[p] - M * (2 - r[p, b] - r[pp, b]),
                        name=f"rack_seq_fixed_order[{p},{pp},{b}]",
                    )

    # ---------------------------------------------------------
    # 4.11 Order completion time
    # ---------------------------------------------------------

    for o in O:
        for p in P:
            model.addConstr(
                Co[o] >= Dp[p] - M * (1 - x[p, o]),
                name=f"order_completion[{o},{p}]",
            )

    # ---------------------------------------------------------
    # 4.12 Makespan
    # ---------------------------------------------------------

    for o in O:
        model.addConstr(Cmax >= Co[o], name=f"makespan[{o}]")

    # =========================================================
    # 5. Solver parameters
    # =========================================================

    model.Params.TimeLimit = time_limit
    model.Params.MIPGap = mip_gap
    model.Params.OutputFlag = output_flag

    variables: dict[str, Any] = {
        "x": x,
        "y": y,
        "m": m,
        "r": r,
        "S": S,
        "E": E,
        "H": H,
        "Grel": Grel,
        "Dp": Dp,
        "F": F,
        "Wamr": Wamr,
        "Co": Co,
        "Cmax": Cmax,
        "rack_of_cp": rack_of_cp,
    }

    return model, variables


def optimize_model(model: gp.Model) -> bool:
    """Optimize model and return True if at least one feasible solution is found."""
    model.optimize()

    if model.SolCount == 0:
        print("\nNo feasible solution found.")
        if model.Status == GRB.INFEASIBLE:
            print("Model is infeasible. Computing IIS...")
            model.computeIIS()
            model.write("infeasible_model.ilp")
            print("IIS written to infeasible_model.ilp")
        return False

    print("\n==============================")
    print("Solution Summary")
    print("==============================")
    print(f"Status     : {model.Status}")
    print(f"Objective  : {model.ObjVal:.4f}")
    print(f"Best Bound : {model.ObjBound:.4f}")
    print(f"MIP Gap    : {model.MIPGap:.6f}")
    print(f"Runtime    : {model.Runtime:.2f} sec")
    return True


def print_solution(
    *,
    P: list[int],
    O: list[int],
    B: list[int],
    C_b: dict[int, list[int]],
    g_p: dict[int, str],
    l_p: dict[int, int],
    amr_of_piece: dict[int, int],
    variables: dict[str, Any],
) -> None:
    """Print main optimization results in a readable format."""

    x = variables["x"]
    y = variables["y"]
    m = variables["m"]
    r = variables["r"]
    S = variables["S"]
    E = variables["E"]
    H = variables["H"]
    Grel = variables["Grel"]
    Dp = variables["Dp"]
    F = variables["F"]
    Wamr = variables["Wamr"]
    Co = variables["Co"]
    Cmax = variables["Cmax"]
    rack_of_cp = variables["rack_of_cp"]

    C = [c for cps in C_b.values() for c in cps]
    C.sort()

    print("\n==============================")
    print("Cmax")
    print("==============================")
    print(f"Cmax = {Cmax.X:.2f}")

    print("\n==============================")
    print("Order -> CP assignment")
    print("==============================")
    for o in O:
        assigned_cp = [c for c in C if y[o, c].X > 0.5][0]
        assigned_rack = rack_of_cp[assigned_cp]
        print(
            f"Order {o:2d} -> CP {assigned_cp:2d} "
            f"(Rack {assigned_rack}) | C_order = {Co[o].X:.2f}"
        )

    print("\n==============================")
    print("Piece assignment and timing")
    print("==============================")
    print(
        "p | SKU | LS | AMR | Order | CP | Rack | "
        "S | E | H | G | D | F | AMR_wait"
    )

    for p in P:
        assigned_order = [o for o in O if x[p, o].X > 0.5][0]
        assigned_cp = [c for c in C if m[p, c].X > 0.5][0]
        assigned_rack = [b for b in B if r[p, b].X > 0.5][0]
        print(
            f"{p:2d} | {g_p[p]:>16s} | {l_p[p]:2d} | {amr_of_piece[p]:3d} | "
            f"{assigned_order:5d} | {assigned_cp:2d} | {assigned_rack:4d} | "
            f"{S[p].X:5.1f} | {E[p].X:5.1f} | {H[p].X:5.1f} | "
            f"{Grel[p].X:5.1f} | {Dp[p].X:5.1f} | {F[p].X:5.1f} | "
            f"{Wamr[p].X:8.1f}"
        )

    print("\n==============================")
    print("Rack/Shuttle processing sequence")
    print("==============================")

    for b in B:
        pieces_in_rack = [p for p in P if r[p, b].X > 0.5]
        pieces_in_rack.sort(key=lambda p: H[p].X)

        print(f"\nRack {b}:")
        for p in pieces_in_rack:
            assigned_cp = [c for c in C if m[p, c].X > 0.5][0]
            print(
                f"  Piece {p:2d} -> CP {assigned_cp:2d} | "
                f"H={H[p].X:.1f}, D={Dp[p].X:.1f}, F={F[p].X:.1f}, "
                f"AMR_wait={Wamr[p].X:.1f}"
            )
