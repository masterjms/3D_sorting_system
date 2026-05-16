"""
run_decomposition_instance.py

Runner for the two-stage decomposition model.

Then run:
    python DEC_MIP/run_decomposition_instance.py
or:
    cd DEC_MIP
    python run_decomposition_instance.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.instance_data import (
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
from DEC_MIP.model_3d_sorter_decomposition import (
    print_decomposition_solution,
    solve_two_stage_decomposition,
)


def main() -> None:
    P, O, G, g_p, l_p, a_p, d, piece_source = load_orders_and_pieces_from_csv(
        csv_path=CSV_PATH,
        num_csv_rows=NUM_CSV_ROWS,
        rows_per_order=ROWS_PER_ORDER,
    )

    B, C, C_b, tau_LB, tau_BL, tau_BC, rho, h, A_b, A_c = build_layout_and_time_parameters()
    amr_of_piece, K_AMR, S0 = build_fixed_amr_assignment(P=P, a_p=a_p)

    validate_instance(P=P, O=O, G=G, C=C, C_b=C_b, g_p=g_p, d=d)

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

    result = solve_two_stage_decomposition(
        P=P,
        O=O,
        G=G,
        C=C,
        B=B,
        C_b=C_b,
        g_p=g_p,
        l_p=l_p,
        d=d,
        tau_LB=tau_LB,
        tau_BL=tau_BL,
        tau_BC=tau_BC,
        rho=rho,
        h=h,
        A_b=A_b,
        A_c=A_c,
        S0=S0,
        K_AMR=K_AMR,
        big_m=BIG_M,
        p2o_time_limit=TIME_LIMIT,
        stage2_time_limit=TIME_LIMIT,
        mip_gap=MIP_GAP,
        output_flag=OUTPUT_FLAG,
    )

    if result is not None:
        print_decomposition_solution(
            P=P,
            O=O,
            B=B,
            C_b=C_b,
            g_p=g_p,
            l_p=l_p,
            amr_of_piece=amr_of_piece,
            result=result,
        )


if __name__ == "__main__":
    main()
