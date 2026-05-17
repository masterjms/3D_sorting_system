"""
run_rack_aware_hors_instance.py

Runner for rack-aware integrated 3D-HORS-MIP.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ------------------------------------------------------------
# Path setup
# ------------------------------------------------------------

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
COMMON_DIR = PROJECT_ROOT / "common"

for path in [THIS_DIR, COMMON_DIR, PROJECT_ROOT]:
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

# ------------------------------------------------------------
# Imports from your existing common/instance_data.py
# ------------------------------------------------------------

from instance_data import (  # type: ignore
    BIG_M,
    CSV_PATH,
    MIP_GAP,
    NUM_CSV_ROWS,
    OUTPUT_FLAG,
    ROWS_PER_ORDER,
    TIME_LIMIT,
    build_fixed_amr_assignment,
    build_layout_and_time_parameters,
    load_orders_and_pieces_from_csv,
    print_instance_summary,
    validate_instance,
)

from rack_aware_hors_mip import (  # type: ignore
    build_rack_aware_hors_mip,
    optimize_model,
    print_rack_aware_hors_solution,
)


def main() -> None:
    # --------------------------------------------------------
    # 1. Build instance from E-Commerce DataSet.xlsx
    # --------------------------------------------------------

    P, O, G, g_p, l_p, a_p, d, piece_source = load_orders_and_pieces_from_csv(
        CSV_PATH,
        NUM_CSV_ROWS,
        ROWS_PER_ORDER,
    )

    # Existing instance_data.py returns A_b and A_c.
    # Static instances usually set them to zero, while rolling-horizon
    # instances can use them to represent currently occupied racks/CPs.
    B, C, C_b, tau_LB, tau_BL, tau_BC, rho, h, _A_b, _A_c = (
        build_layout_and_time_parameters()
    )

    amr_of_piece, K_AMR, S0 = build_fixed_amr_assignment(P, a_p)

    validate_instance(
        P=P,
        O=O,
        G=G,
        C=C,
        C_b=C_b,
        g_p=g_p,
        d=d,
    )

    print_instance_summary(
        P=P,
        O=O,
        G=G,
        B=B,
        C=C,
        C_b=C_b,
        g_p=g_p,
        l_p=l_p,
        a_p=a_p,
        d=d,
        amr_of_piece=amr_of_piece,
        piece_source=piece_source,
    )

    # --------------------------------------------------------
    # 2. Build and solve rack-aware integrated HORS-MIP
    # --------------------------------------------------------

    model, variables = build_rack_aware_hors_mip(
        P=P,
        O=O,
        G=G,
        B=B,
        C=C,
        C_b=C_b,
        g_p=g_p,
        l_p=l_p,
        d=d,
        tau_LB=tau_LB,
        tau_BL=tau_BL,
        tau_BC=tau_BC,
        rho=rho,
        h=h,
        S0=S0,
        K_AMR=K_AMR,
        big_m=BIG_M,
        time_limit=TIME_LIMIT,
        mip_gap=MIP_GAP,
        output_flag=OUTPUT_FLAG,
    )

    solved = optimize_model(model, iis_filename="rack_aware_hors_infeasible.ilp")

    if not solved:
        return

    # --------------------------------------------------------
    # 3. Print solution
    # --------------------------------------------------------

    print_rack_aware_hors_solution(
        P=P,
        O=O,
        B=B,
        C=C,
        C_b=C_b,
        g_p=g_p,
        l_p=l_p,
        amr_of_piece=amr_of_piece,
        variables=variables,
    )


if __name__ == "__main__":
    main()
