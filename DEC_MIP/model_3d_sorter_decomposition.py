"""
model_3d_sorter_decomposition.py

Two-stage decomposition model for the 3D Robotized Sorting System.

Stage 1: P2O MIP
- Decide piece-to-order assignment x[p,o].
- Use an order-spread objective as a surrogate objective.

Stage 2: O2CP + Timing integrated MIP
- Fix x[p,o] from Stage 1.
- Decide order-to-CP y[o,c], piece-to-CP m[p,c], piece-to-rack r[p,b].
- Optimize AMR/shuttle timing and Cmax.

This file is designed to work with the shared data structures built by
common.instance_data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gurobipy as gp
from gurobipy import GRB


@dataclass(frozen=True)
class P2OResult:
    """Stage-1 result."""

    x_fixed: dict[tuple[int, int], int]
    order_of_piece: dict[int, int]
    first_pos: dict[int, float]
    last_pos: dict[int, float]
    spread: dict[int, float]
    objective: float


@dataclass(frozen=True)
class DecompositionResult:
    """Final two-stage decomposition result."""

    p2o: P2OResult
    stage2_model: gp.Model
    stage2_variables: dict[str, Any]


# ============================================================
# Common helpers
# ============================================================


def build_rack_of_cp(B: list[int], C: list[int], C_b: dict[int, list[int]]) -> dict[int, int]:
    """Return rack_of_cp[c] = b after validating CP membership."""

    cp_seen: list[int] = []
    for b in B:
        if b not in C_b:
            raise ValueError(f"Missing C_b entry for rack {b}.")
        cp_seen.extend(C_b[b])

    if set(cp_seen) != set(C):
        raise ValueError("Every CP must belong to exactly one rack in C_b.")

    if len(cp_seen) != len(set(cp_seen)):
        raise ValueError("A CP appears in more than one rack in C_b.")

    return {c: b for b in B for c in C_b[b]}


def optimize_model(model: gp.Model, *, iis_filename: str = "infeasible_model.ilp") -> bool:
    """Optimize model and return True if at least one feasible solution is found."""

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


# ============================================================
# Stage 1. P2O MIP
# ============================================================


def build_p2o_mip(
    *,
    P: list[int],
    O: list[int],
    G: list[str],
    g_p: dict[int, str],
    d: dict[tuple[int, str], int],
    piece_position: dict[int, int] | None = None,
    big_m: float = 10000.0,
    time_limit: float = 300.0,
    mip_gap: float = 0.01,
    output_flag: int = 1,
) -> tuple[gp.Model, dict[str, Any]]:
    """
    Build Stage-1 P2O MIP.

    Decision:
    - x[p,o] = 1 if piece p is assigned to order o.

    Objective:
    - Minimize total order spread.
      The spread of order o is approximated by last_pos[o] - first_pos[o] + 1.
      This follows the decomposition idea that compact order spans are useful
      for downstream CP assignment.

    Notes:
    - This stage does not know CP/rack/timing decisions yet.
    - Therefore it does not minimize Cmax directly.
    """

    if piece_position is None:
        # Default limited-lookahead sequence is the piece index/order.
        piece_position = {p: idx for idx, p in enumerate(sorted(P))}

    model = gp.Model("Stage1_P2O_OrderSpread_MIP")
    M = big_m

    x = model.addVars(P, O, vtype=GRB.BINARY, name="x_piece_order")

    # first_pos[o] and last_pos[o] describe the interval occupied by order o
    # in the lookahead sequence.
    max_pos = max(piece_position.values()) if P else 0
    first_pos = model.addVars(O, lb=0, ub=max_pos, vtype=GRB.CONTINUOUS, name="first_pos")
    last_pos = model.addVars(O, lb=0, ub=max_pos, vtype=GRB.CONTINUOUS, name="last_pos")
    spread = model.addVars(O, lb=0, vtype=GRB.CONTINUOUS, name="order_spread")

    # Each piece is assigned to exactly one order.
    for p in P:
        model.addConstr(
            gp.quicksum(x[p, o] for o in O) == 1,
            name=f"one_order_per_piece[{p}]",
        )

    # SKU compatibility.
    for p in P:
        for o in O:
            if d.get((o, g_p[p]), 0) == 0:
                model.addConstr(
                    x[p, o] == 0,
                    name=f"incompatible_piece_order[{p},{o}]",
                )

    # Demand must be exactly satisfied in the decomposed P2O stage.
    # The original compact model used <=, but because total supply equals total
    # demand and each piece is assigned once, equality is the cleaner P2O form.
    for o in O:
        for sku in G:
            model.addConstr(
                gp.quicksum(x[p, o] for p in P if g_p[p] == sku)
                == d.get((o, sku), 0),
                name=f"demand_exact[{o},{sku}]",
            )

    # Order spread constraints.
    # If x[p,o] = 1, then:
    #   first_pos[o] <= pos[p]
    #   last_pos[o]  >= pos[p]
    # The objective pushes first_pos up and last_pos down, producing the
    # tightest interval for assigned pieces.
    for p in P:
        pos = piece_position[p]
        for o in O:
            model.addConstr(
                first_pos[o] <= pos + M * (1 - x[p, o]),
                name=f"first_before_assigned_piece[{p},{o}]",
            )
            model.addConstr(
                last_pos[o] >= pos - M * (1 - x[p, o]),
                name=f"last_after_assigned_piece[{p},{o}]",
            )

    for o in O:
        model.addConstr(
            spread[o] >= last_pos[o] - first_pos[o] + 1,
            name=f"spread_def[{o}]",
        )

    model.setObjective(gp.quicksum(spread[o] for o in O), GRB.MINIMIZE)

    model.Params.TimeLimit = time_limit
    model.Params.MIPGap = mip_gap
    model.Params.OutputFlag = output_flag

    variables: dict[str, Any] = {
        "x": x,
        "first_pos": first_pos,
        "last_pos": last_pos,
        "spread": spread,
        "piece_position": piece_position,
    }

    return model, variables


def extract_p2o_result(
    *,
    P: list[int],
    O: list[int],
    variables: dict[str, Any],
) -> P2OResult:
    """Extract fixed x[p,o] and order_of_piece from a solved P2O model."""

    x = variables["x"]
    first_pos = variables["first_pos"]
    last_pos = variables["last_pos"]
    spread_var = variables["spread"]

    x_fixed: dict[tuple[int, int], int] = {}
    order_of_piece: dict[int, int] = {}

    for p in P:
        assigned_orders = [o for o in O if x[p, o].X > 0.5]
        if len(assigned_orders) != 1:
            raise ValueError(f"Piece {p} has invalid P2O assignment: {assigned_orders}")
        assigned_order = assigned_orders[0]
        order_of_piece[p] = assigned_order
        for o in O:
            x_fixed[p, o] = 1 if o == assigned_order else 0

    spread = {o: spread_var[o].X for o in O}
    first = {o: first_pos[o].X for o in O}
    last = {o: last_pos[o].X for o in O}
    objective = sum(spread.values())

    return P2OResult(
        x_fixed=x_fixed,
        order_of_piece=order_of_piece,
        first_pos=first,
        last_pos=last,
        spread=spread,
        objective=objective,
    )


# ============================================================
# Stage 2. O2CP + Timing integrated MIP
# ============================================================


def build_o2cp_timing_mip(
    *,
    P: list[int],
    O: list[int],
    C: list[int],
    B: list[int],
    C_b: dict[int, list[int]],
    order_of_piece: dict[int, int],
    l_p: dict[int, int],
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
    Build Stage-2 O2CP + Timing integrated MIP.

    Fixed from Stage 1:
    - order_of_piece[p] = assigned order of piece p.

    Decision:
    - y[o,c]: order-to-CP assignment
    - m[p,c]: piece-to-CP assignment induced by y[order_of_piece[p], c]
    - r[p,b]: piece-to-rack assignment induced by m and C_b
    - timing variables S, E, H, Grel, Dp, F, Wamr, Co, Cmax

    Objective:
    - Minimize Cmax.
    """

    if len(O) > len(C):
        raise ValueError(
            "No CP reuse is allowed. Therefore |O| must be <= |C|. "
            f"Got |O|={len(O)}, |C|={len(C)}."
        )

    rack_of_cp = build_rack_of_cp(B=B, C=C, C_b=C_b)

    model = gp.Model("Stage2_O2CP_Timing_Integrated_MIP")
    M = big_m

    # O2CP and induced assignment variables.
    y = model.addVars(O, C, vtype=GRB.BINARY, name="y_order_cp")
    m = model.addVars(P, C, vtype=GRB.BINARY, name="m_piece_cp")
    r = model.addVars(P, B, vtype=GRB.BINARY, name="r_piece_rack")

    # Timing variables.
    S = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="S_amr_start")
    E = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="E_amr_arrive_rack")
    H = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="H_handover_start")
    Grel = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="G_amr_release")
    Dp = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="D_piece_cp_done")
    F = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="F_shuttle_release")
    Wamr = model.addVars(P, lb=0, vtype=GRB.CONTINUOUS, name="W_amr_wait")

    Co = model.addVars(O, lb=0, vtype=GRB.CONTINUOUS, name="C_order")
    Cmax = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="Cmax")

    model.setObjective(Cmax, GRB.MINIMIZE)

    # --------------------------------------------------------
    # O2CP assignment
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Since P2O is fixed, m[p,c] = y[order_of_piece[p], c]
    # --------------------------------------------------------

    for p in P:
        if p not in order_of_piece:
            raise ValueError(f"Missing fixed order assignment for piece {p}.")
        assigned_order = order_of_piece[p]
        if assigned_order not in O:
            raise ValueError(f"Invalid fixed order {assigned_order} for piece {p}.")

        for c in C:
            model.addConstr(
                m[p, c] == y[assigned_order, c],
                name=f"m_fixed_by_p2o_and_y[{p},{c}]",
            )

        model.addConstr(
            gp.quicksum(m[p, c] for c in C) == 1,
            name=f"one_cp_per_piece[{p}]",
        )

    # --------------------------------------------------------
    # Piece-to-rack linking
    # --------------------------------------------------------

    for p in P:
        for b in B:
            model.addConstr(
                r[p, b] == gp.quicksum(m[p, c] for c in C_b[b]),
                name=f"piece_rack_link[{p},{b}]",
            )
        model.addConstr(
            gp.quicksum(r[p, b] for b in B) == 1,
            name=f"one_rack_per_piece[{p}]",
        )

    # --------------------------------------------------------
    # AMR start and rack arrival time
    # --------------------------------------------------------

    for p in P:
        model.addConstr(
            S[p] >= S0[p],
            name=f"amr_start_after_piece_available[{p}]",
        )
        model.addConstr(
            E[p] >= S[p] + gp.quicksum(tau_LB[l_p[p], b] * r[p, b] for b in B),
            name=f"amr_arrival_at_rack[{p}]",
        )

    # --------------------------------------------------------
    # No-buffer direct handover constraints
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Same AMR consecutive job constraints
    # --------------------------------------------------------

    for p, pp in K_AMR:
        model.addConstr(
            S[pp]
            >= Grel[p] + gp.quicksum(tau_BL[b, l_p[pp]] * r[p, b] for b in B),
            name=f"same_amr_next_job[{p},{pp}]",
        )

    # --------------------------------------------------------
    # CP availability
    # --------------------------------------------------------

    for p in P:
        model.addConstr(
            Dp[p] >= gp.quicksum(A_c[c] * m[p, c] for c in C),
            name=f"cp_initial_available[{p}]",
        )

    # --------------------------------------------------------
    # Rack/shuttle processing time
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Rack/shuttle single-processing sequencing
    #
    # Because Stage 2 still decides y/m/r, r[p,b] is not fixed here.
    # Therefore the Big-M sequencing logic from the compact HORS MIP is kept.
    # --------------------------------------------------------

    for p in P:
        for pp in P:
            if p < pp:
                for b in B:
                    model.addConstr(
                        H[pp]
                        >= F[p] - M * (2 - r[p, b] - r[pp, b]),
                        name=f"rack_seq_fixed_order[{p},{pp},{b}]",
                    )

    # --------------------------------------------------------
    # Order completion time
    # --------------------------------------------------------

    for o in O:
        assigned_pieces = [p for p in P if order_of_piece[p] == o]
        if not assigned_pieces:
            raise ValueError(f"Order {o} has no assigned pieces after P2O.")
        for p in assigned_pieces:
            model.addConstr(
                Co[o] >= Dp[p],
                name=f"order_completion_fixed_p2o[{o},{p}]",
            )

    for o in O:
        model.addConstr(Cmax >= Co[o], name=f"makespan[{o}]")

    model.Params.TimeLimit = time_limit
    model.Params.MIPGap = mip_gap
    model.Params.OutputFlag = output_flag

    variables: dict[str, Any] = {
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
        "order_of_piece": order_of_piece,
    }

    return model, variables


# ============================================================
# Solver pipeline and printing
# ============================================================


def solve_two_stage_decomposition(
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
    p2o_time_limit: float = 300.0,
    stage2_time_limit: float = 300.0,
    mip_gap: float = 0.01,
    output_flag: int = 1,
) -> DecompositionResult | None:
    """Run Stage 1 P2O and Stage 2 O2CP+Timing in sequence."""

    print("\n==============================")
    print("Stage 1: P2O MIP")
    print("==============================")

    p2o_model, p2o_vars = build_p2o_mip(
        P=P,
        O=O,
        G=G,
        g_p=g_p,
        d=d,
        big_m=big_m,
        time_limit=p2o_time_limit,
        mip_gap=mip_gap,
        output_flag=output_flag,
    )

    if not optimize_model(p2o_model, iis_filename="p2o_infeasible.ilp"):
        return None

    p2o_result = extract_p2o_result(P=P, O=O, variables=p2o_vars)
    print_p2o_solution(P=P, O=O, g_p=g_p, p2o=p2o_result)

    print("\n==============================")
    print("Stage 2: O2CP + Timing Integrated MIP")
    print("==============================")

    stage2_model, stage2_vars = build_o2cp_timing_mip(
        P=P,
        O=O,
        C=C,
        B=B,
        C_b=C_b,
        order_of_piece=p2o_result.order_of_piece,
        l_p=l_p,
        tau_LB=tau_LB,
        tau_BL=tau_BL,
        tau_BC=tau_BC,
        rho=rho,
        h=h,
        A_b=A_b,
        A_c=A_c,
        S0=S0,
        K_AMR=K_AMR,
        big_m=big_m,
        time_limit=stage2_time_limit,
        mip_gap=mip_gap,
        output_flag=output_flag,
    )

    if not optimize_model(stage2_model, iis_filename="stage2_infeasible.ilp"):
        return None

    return DecompositionResult(
        p2o=p2o_result,
        stage2_model=stage2_model,
        stage2_variables=stage2_vars,
    )


def print_p2o_solution(
    *,
    P: list[int],
    O: list[int],
    g_p: dict[int, str],
    p2o: P2OResult,
) -> None:
    """Print Stage-1 P2O result."""

    print("\n==============================")
    print("P2O result")
    print("==============================")
    print(f"Total spread objective = {p2o.objective:.2f}")

    print("\nOrder spread")
    for o in O:
        print(
            f"Order {o:2d}: first={p2o.first_pos[o]:5.1f}, "
            f"last={p2o.last_pos[o]:5.1f}, spread={p2o.spread[o]:5.1f}"
        )

    print("\nPiece -> Order assignment")
    print("p | SKU | Order")
    for p in P:
        print(f"{p:2d} | {g_p[p]:16s} | {p2o.order_of_piece[p]:5d}")


def print_decomposition_solution(
    *,
    P: list[int],
    O: list[int],
    B: list[int],
    C_b: dict[int, list[int]],
    g_p: dict[int, str],
    l_p: dict[int, int],
    amr_of_piece: dict[int, int],
    result: DecompositionResult,
) -> None:
    """Print final two-stage decomposition result."""

    variables = result.stage2_variables
    p2o = result.p2o

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
    print("Two-stage decomposition final result")
    print("==============================")
    print(f"Stage 1 P2O spread objective = {p2o.objective:.2f}")
    print(f"Stage 2 Cmax                 = {Cmax.X:.2f}")

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
        assigned_order = p2o.order_of_piece[p]
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
                f"Order={p2o.order_of_piece[p]:2d}, "
                f"H={H[p].X:.1f}, D={Dp[p].X:.1f}, F={F[p].X:.1f}, "
                f"AMR_wait={Wamr[p].X:.1f}"
            )
