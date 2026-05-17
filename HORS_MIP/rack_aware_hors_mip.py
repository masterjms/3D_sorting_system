"""
rack_aware_hors_mip.py

Integrated 3D-HORS-MIP with explicit Order-to-Shuttle/Rack layer.

This model follows the formulation:

    Piece -> Order -> Rack/Shuttle -> CP -> Timing

Key points:
- O2ST is represented by z[o,b].
- ST2CP is optimized by y[o,c], not FCFS.
- u[p,o,b] is intentionally NOT used.
- Piece-to-rack r[p,b] is derived through CP assignment:
      r[p,b] = sum_{c in C_b} m[p,c]
- Objective is pure min Cmax. No auxiliary/tie-break objective is used.
- A_b and A_c initial availability parameters are used for rolling-horizon availability constraints.
"""

from __future__ import annotations

from typing import Any

import gurobipy as gp
from gurobipy import GRB


def build_rack_of_cp(
    *,
    B: list[int],
    C: list[int],
    C_b: dict[int, list[int]],
) -> dict[int, int]:
    """Build b(c): CP -> rack mapping and validate C_b."""
    cp_seen: list[int] = []

    for b in B:
        if b not in C_b:
            raise ValueError(f"Missing C_b entry for rack {b}.")
        cp_seen.extend(C_b[b])

    if set(cp_seen) != set(C):
        raise ValueError("C_b must cover exactly all CPs in C.")

    if len(cp_seen) != len(set(cp_seen)):
        raise ValueError("Each CP must belong to exactly one rack.")

    return {c: b for b in B for c in C_b[b]}


def build_rack_aware_hors_mip(
    *,
    P: list[int],
    O: list[int],
    G: list[str],
    B: list[int],
    C: list[int],
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
    time_limit: float = 500.0,
    mip_gap: float = 0.01,
    output_flag: int = 1,
) -> tuple[gp.Model, dict[str, Any]]:
    """
    Build integrated rack-aware HORS-MIP.

    Decisions:
    - x[p,o]: piece-to-order
    - z[o,b]: order-to-rack/shuttle
    - y[o,c]: order-to-CP within selected rack
    - m[p,c]: piece-to-CP
    - r[p,b]: piece-to-rack, derived from m
    - S,E,H,Grel,Dp,F,Wamr,Co,Cmax timing/completion

    Objective:
    - min Cmax
    """

    if len(O) > len(C):
        raise ValueError(
            "No CP reuse is assumed. Therefore |O| must be <= |C|. "
            f"Got |O|={len(O)}, |C|={len(C)}."
        )

    rack_of_cp = build_rack_of_cp(B=B, C=C, C_b=C_b)

    # Availability parameter validation. In static benchmark instances,
    # these are usually all zero. In rolling-horizon settings, they can
    # represent already occupied racks/shuttles or CPs.
    missing_A_b = [b for b in B if b not in A_b]
    missing_A_c = [c for c in C if c not in A_c]
    if missing_A_b:
        raise ValueError(f"Missing A_b values for racks: {missing_A_b}")
    if missing_A_c:
        raise ValueError(f"Missing A_c values for CPs: {missing_A_c}")

    model = gp.Model("RackAware_Integrated_3D_HORS_MIP")
    M = big_m

    # ------------------------------------------------------------
    # Assignment variables
    # ------------------------------------------------------------

    x = model.addVars(P, O, vtype=GRB.BINARY, name="x_piece_order")
    z = model.addVars(O, B, vtype=GRB.BINARY, name="z_order_rack")
    y = model.addVars(O, C, vtype=GRB.BINARY, name="y_order_cp")
    m = model.addVars(P, C, vtype=GRB.BINARY, name="m_piece_cp")
    r = model.addVars(P, B, vtype=GRB.BINARY, name="r_piece_rack")

    # ------------------------------------------------------------
    # Timing variables
    # ------------------------------------------------------------

    S = model.addVars(P, lb=0.0, vtype=GRB.CONTINUOUS, name="S_amr_start")
    E = model.addVars(P, lb=0.0, vtype=GRB.CONTINUOUS, name="E_amr_arrive_rack")
    H = model.addVars(P, lb=0.0, vtype=GRB.CONTINUOUS, name="H_handover_start")
    Grel = model.addVars(P, lb=0.0, vtype=GRB.CONTINUOUS, name="G_amr_release")
    Dp = model.addVars(P, lb=0.0, vtype=GRB.CONTINUOUS, name="D_piece_cp_done")
    F = model.addVars(P, lb=0.0, vtype=GRB.CONTINUOUS, name="F_shuttle_release")
    Wamr = model.addVars(P, lb=0.0, vtype=GRB.CONTINUOUS, name="W_amr_wait")

    Co = model.addVars(O, lb=0.0, vtype=GRB.CONTINUOUS, name="C_order")
    Cmax = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="Cmax")

    # ------------------------------------------------------------
    # 1. Piece-to-order assignment
    # ------------------------------------------------------------

    for p in P:
        model.addConstr(
            gp.quicksum(x[p, o] for o in O) == 1,
            name=f"one_order_per_piece[{p}]",
        )

    # Exact SKU demand satisfaction
    for o in O:
        for sku in G:
            model.addConstr(
                gp.quicksum(x[p, o] for p in P if g_p[p] == sku)
                == d.get((o, sku), 0),
                name=f"sku_demand_exact[{o},{sku}]",
            )

    # ------------------------------------------------------------
    # 2. O2ST: order-to-rack/shuttle
    # ------------------------------------------------------------

    for o in O:
        model.addConstr(
            gp.quicksum(z[o, b] for b in B) == 1,
            name=f"one_rack_per_order[{o}]",
        )

    # Rack capacity by number of CPs, no CP reuse
    for b in B:
        model.addConstr(
            gp.quicksum(z[o, b] for o in O) <= len(C_b[b]),
            name=f"rack_order_capacity[{b}]",
        )

    # ------------------------------------------------------------
    # 3. ST2CP: order-to-CP, optimized
    # ------------------------------------------------------------

    for o in O:
        model.addConstr(
            gp.quicksum(y[o, c] for c in C) == 1,
            name=f"one_cp_per_order[{o}]",
        )

    # No CP reuse
    for c in C:
        model.addConstr(
            gp.quicksum(y[o, c] for o in O) <= 1,
            name=f"one_order_per_cp[{c}]",
        )

    # O2ST-ST2CP linking:
    # order o assigned to rack b iff its selected CP belongs to C_b
    for o in O:
        for b in B:
            model.addConstr(
                gp.quicksum(y[o, c] for c in C_b[b]) == z[o, b],
                name=f"order_rack_cp_link[{o},{b}]",
            )

    # ------------------------------------------------------------
    # 4. Piece-to-CP linking: m[p,c] = sum_o x[p,o] * y[o,c]
    # ------------------------------------------------------------

    for p in P:
        for c in C:
            for o in O:
                model.addConstr(
                    m[p, c] >= x[p, o] + y[o, c] - 1,
                    name=f"piece_cp_lb[{p},{o},{c}]",
                )
                model.addConstr(
                    m[p, c] <= x[p, o] + 1 - y[o, c],
                    name=f"piece_cp_ub1[{p},{o},{c}]",
                )
                model.addConstr(
                    m[p, c] <= y[o, c] + 1 - x[p, o],
                    name=f"piece_cp_ub2[{p},{o},{c}]",
                )

        model.addConstr(
            gp.quicksum(m[p, c] for c in C) == 1,
            name=f"one_cp_per_piece[{p}]",
        )

    # ------------------------------------------------------------
    # 5. Piece-to-rack linking through CP assignment
    # ------------------------------------------------------------

    for p in P:
        for b in B:
            model.addConstr(
                r[p, b] == gp.quicksum(m[p, c] for c in C_b[b]),
                name=f"piece_rack_from_cp[{p},{b}]",
            )

        model.addConstr(
            gp.quicksum(r[p, b] for b in B) == 1,
            name=f"one_rack_per_piece[{p}]",
        )

    # ------------------------------------------------------------
    # 6. AMR timing
    # ------------------------------------------------------------

    for p in P:
        model.addConstr(
            S[p] >= S0[p],
            name=f"piece_available_before_start[{p}]",
        )

        model.addConstr(
            E[p]
            == S[p]
            + gp.quicksum(tau_LB[l_p[p], b] * r[p, b] for b in B),
            name=f"amr_arrival_exact[{p}]",
        )

        model.addConstr(
            H[p] >= E[p],
            name=f"handover_after_amr_arrival[{p}]",
        )

        model.addConstr(
            H[p] >= gp.quicksum(A_b[b] * r[p, b] for b in B),
            name=f"handover_after_rack_available[{p}]",
        )

        model.addConstr(
            Grel[p]
            == H[p] + gp.quicksum(h[b] * r[p, b] for b in B),
            name=f"amr_release_exact[{p}]",
        )

        model.addConstr(
            Wamr[p] == H[p] - E[p],
            name=f"amr_wait_exact[{p}]",
        )

    for p, pp in K_AMR:
        model.addConstr(
            S[pp]
            >= Grel[p]
            + gp.quicksum(tau_BL[b, l_p[pp]] * r[p, b] for b in B),
            name=f"same_amr_consecutive_job[{p},{pp}]",
        )

    # ------------------------------------------------------------
    # 7. Shuttle CP completion and release timing
    # ------------------------------------------------------------

    for p in P:
        model.addConstr(
            Dp[p]
            == H[p]
            + gp.quicksum(
                (h[rack_of_cp[c]] + tau_BC[rack_of_cp[c], c]) * m[p, c]
                for c in C
            ),
            name=f"piece_cp_completion_exact[{p}]",
        )

        model.addConstr(
            Dp[p] >= gp.quicksum(A_c[c] * m[p, c] for c in C),
            name=f"piece_after_cp_available[{p}]",
        )

        model.addConstr(
            F[p]
            == H[p]
            + gp.quicksum(
                (
                    h[rack_of_cp[c]]
                    + tau_BC[rack_of_cp[c], c]
                    + rho[rack_of_cp[c], c]
                )
                * m[p, c]
                for c in C
            ),
            name=f"shuttle_release_exact[{p}]",
        )

    # ------------------------------------------------------------
    # 8. Same rack single-shuttle sequencing
    # ------------------------------------------------------------

    for p in P:
        for pp in P:
            if p < pp:
                for b in B:
                    model.addConstr(
                        H[pp] >= F[p] - M * (2 - r[p, b] - r[pp, b]),
                        name=f"same_rack_sequence[{p},{pp},{b}]",
                    )

    # ------------------------------------------------------------
    # 9. Order completion and makespan
    # ------------------------------------------------------------

    for o in O:
        for p in P:
            model.addConstr(
                Co[o] >= Dp[p] - M * (1 - x[p, o]),
                name=f"order_completion[{o},{p}]",
            )

    for o in O:
        model.addConstr(
            Cmax >= Co[o],
            name=f"makespan_ge_order_completion[{o}]",
        )

    # ------------------------------------------------------------
    # Objective: pure Cmax minimization
    # ------------------------------------------------------------

    model.setObjective(Cmax, GRB.MINIMIZE)

    model.Params.TimeLimit = time_limit
    model.Params.MIPGap = mip_gap
    model.Params.OutputFlag = output_flag

    variables: dict[str, Any] = {
        "x": x,
        "z": z,
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


def optimize_model(
    model: gp.Model,
    *,
    iis_filename: str = "rack_aware_hors_infeasible.ilp",
) -> bool:
    """Optimize model and return True if a feasible solution is found."""
    model.optimize()

    if model.SolCount == 0:
        print("\nNo feasible solution found.")

        if model.Status == GRB.INFEASIBLE:
            print("Model is infeasible. Computing IIS...")
            model.computeIIS()
            model.write(iis_filename)
            print(f"IIS written to {iis_filename}")

        return False

    print("\n==============================")
    print("Solution Summary")
    print("==============================")
    print(f"Model      : {model.ModelName}")
    print(f"Status     : {model.Status}")
    print(f"Objective  : {model.ObjVal:.4f}")
    print(f"Best Bound : {model.ObjBound:.4f}")
    print(f"MIP Gap    : {model.MIPGap:.6f}")
    print(f"Runtime    : {model.Runtime:.2f} sec")

    return True


def print_rack_aware_hors_solution(
    *,
    P: list[int],
    O: list[int],
    B: list[int],
    C: list[int],
    C_b: dict[int, list[int]],
    g_p: dict[int, str],
    l_p: dict[int, int],
    amr_of_piece: dict[int, int],
    variables: dict[str, Any],
) -> None:
    """Print solution in the same style as previous HORS/DEC outputs."""

    x = variables["x"]
    z = variables["z"]
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

    print("\n==============================")
    print("Cmax")
    print("==============================")
    print(f"Cmax = {Cmax.X:.2f}")

    print("\n==============================")
    print("Order -> Rack/Shuttle -> CP assignment")
    print("==============================")

    for o in O:
        assigned_rack = [b for b in B if z[o, b].X > 0.5]
        assigned_cp = [c for c in C if y[o, c].X > 0.5]

        if len(assigned_rack) != 1 or len(assigned_cp) != 1:
            print(
                f"Order {o:2d}: invalid assignment "
                f"rack={assigned_rack}, cp={assigned_cp}"
            )
            continue

        b = assigned_rack[0]
        c = assigned_cp[0]

        print(
            f"Order {o:2d} -> Rack {b:2d} -> CP {c:2d} "
            f"| C_order = {Co[o].X:.2f}"
        )

    print("\n==============================")
    print("Piece assignment and timing")
    print("==============================")
    print(
        "p | SKU | LS | AMR | Order | Rack | CP | "
        "S | E | H | G | D | F | AMR_wait"
    )

    for p in P:
        assigned_order = [o for o in O if x[p, o].X > 0.5]
        assigned_cp = [c for c in C if m[p, c].X > 0.5]
        assigned_rack = [b for b in B if r[p, b].X > 0.5]

        if len(assigned_order) != 1 or len(assigned_cp) != 1 or len(assigned_rack) != 1:
            print(
                f"{p:2d} | invalid assignment "
                f"order={assigned_order}, rack={assigned_rack}, cp={assigned_cp}"
            )
            continue

        o = assigned_order[0]
        c = assigned_cp[0]
        b = assigned_rack[0]

        print(
            f"{p:2d} | {g_p[p]:>16s} | {l_p[p]:2d} | {amr_of_piece[p]:3d} | "
            f"{o:5d} | {b:4d} | {c:2d} | "
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
            assigned_order = [o for o in O if x[p, o].X > 0.5][0]
            assigned_cp = [c for c in C if m[p, c].X > 0.5][0]

            print(
                f"  Piece {p:2d} -> Order {assigned_order:2d}, CP {assigned_cp:2d} | "
                f"H={H[p].X:.1f}, D={Dp[p].X:.1f}, F={F[p].X:.1f}, "
                f"AMR_wait={Wamr[p].X:.1f}"
            )
