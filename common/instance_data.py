"""Shared data and parameter builders for 3D sorter model instances."""

from __future__ import annotations

import csv
from pathlib import Path

# ============================================================
# 0. Editable experiment settings
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

CSV_CANDIDATES = [
    PROJECT_ROOT / "data" / "Online Sales Data.csv",
    PROJECT_ROOT / "Online Sales Data.csv",
]
CSV_PATH = next((path for path in CSV_CANDIDATES if path.exists()), CSV_CANDIDATES[0])

# Use the first 12 CSV rows for the initial test instance.
# 12 rows produce 4 grouped orders when ROWS_PER_ORDER = 3.
NUM_CSV_ROWS = 12
ROWS_PER_ORDER = 3

# System size, based on the instance summary PDF.
NUM_LOADING_STATIONS = 2
NUM_AMR = 4
NUM_RACKS = 3
CP_PER_RACK = 4

# Piece arrival interval after expanding Units Sold into individual pieces.
TIME_STEP_BETWEEN_PIECES = 2

# Solver settings
BIG_M = 10000
TIME_LIMIT = 500
MIP_GAP = 0.01
OUTPUT_FLAG = 1

# Region -> loading station mapping.
# The CSV has North America / Europe / Asia, while the instance summary uses 2 LS.
REGION_TO_LOADING_STATION = {
    "North America": 0,
    "Europe": 1,
    "Asia": 0,
}


# ============================================================
# 1. CSV to piece/order data
# ============================================================

def load_orders_and_pieces_from_csv(
    csv_path: Path,
    num_csv_rows: int,
    rows_per_order: int,
) -> tuple[
    list[int],
    list[int],
    list[str],
    dict[int, str],
    dict[int, int],
    dict[int, float],
    dict[tuple[int, str], int],
    dict[int, dict[str, str]],
]:
    """
    Convert Online Sales Data.csv into model input data.

    Rules:
    - Product Category is used as SKU.
    - Units Sold is expanded into individual pieces.
    - rows_per_order CSV rows are grouped into one order.
    - Date/Product Name/Transaction ID are used only for trace/debug output.
    """

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise ValueError("CSV file is empty.")

    rows = rows[:num_csv_rows]

    required_columns = [
        "Transaction ID",
        "Date",
        "Product Category",
        "Product Name",
        "Units Sold",
        "Region",
    ]
    for col in required_columns:
        if col not in rows[0]:
            raise ValueError(f"Missing required CSV column: {col}")

    # SKU set: Product Category is used as SKU.
    G = sorted({row["Product Category"] for row in rows})

    # --------------------------------------------------------
    # Order demand generation
    # --------------------------------------------------------

    order_chunks: list[list[dict[str, str]]] = []
    for i in range(0, len(rows), rows_per_order):
        chunk = rows[i : i + rows_per_order]
        if chunk:
            order_chunks.append(chunk)

    O = list(range(len(order_chunks)))

    d: dict[tuple[int, str], int] = {(o, sku): 0 for o in O for sku in G}

    for o, chunk in enumerate(order_chunks):
        for row in chunk:
            sku = row["Product Category"]
            units = int(row["Units Sold"])
            d[o, sku] += units

    # --------------------------------------------------------
    # Piece expansion
    # --------------------------------------------------------

    P: list[int] = []
    g_p: dict[int, str] = {}
    l_p: dict[int, int] = {}
    a_p: dict[int, float] = {}
    piece_source: dict[int, dict[str, str]] = {}

    piece_id = 0
    for row_idx, row in enumerate(rows):
        sku = row["Product Category"]
        units = int(row["Units Sold"])
        region = row["Region"]

        if region not in REGION_TO_LOADING_STATION:
            raise ValueError(f"No loading station mapping for Region={region}")

        loading_station = REGION_TO_LOADING_STATION[region]

        for _ in range(units):
            p = piece_id
            P.append(p)
            g_p[p] = sku
            l_p[p] = loading_station
            a_p[p] = TIME_STEP_BETWEEN_PIECES * p
            piece_source[p] = {
                "csv_row": str(row_idx + 1),
                "transaction_id": row["Transaction ID"],
                "date": row["Date"],
                "product_category": row["Product Category"],
                "product_name": row["Product Name"],
                "region": row["Region"],
            }
            piece_id += 1

    # --------------------------------------------------------
    # Supply-demand validation
    # --------------------------------------------------------

    supply = {sku: 0 for sku in G}
    for p in P:
        supply[g_p[p]] += 1

    demand = {sku: 0 for sku in G}
    for o in O:
        for sku in G:
            demand[sku] += d[o, sku]

    if supply != demand:
        raise ValueError(f"Supply-demand mismatch: supply={supply}, demand={demand}")

    return P, O, G, g_p, l_p, a_p, d, piece_source


# ============================================================
# 2. Layout and time parameters from instance summary
# ============================================================

def build_layout_and_time_parameters() -> tuple[
    list[int],
    list[int],
    dict[int, list[int]],
    dict[tuple[int, int], float],
    dict[tuple[int, int], float],
    dict[tuple[int, int], float],
    dict[tuple[int, int], float],
    dict[int, float],
    dict[int, float],
    dict[int, float],
]:
    """
    Build rack/CP structure and time parameters.

    Based on the instance summary:
    - 3 racks
    - 4 CPs per rack
    - 12 CPs total
    - rack handover time = 2 sec
    - shuttle-to-CP times = 7, 9, 11, 13 by CP slot
    - return time is symmetric
    """

    B = list(range(NUM_RACKS))
    C = list(range(NUM_RACKS * CP_PER_RACK))

    C_b: dict[int, list[int]] = {}
    cp_id = 0
    for b in B:
        C_b[b] = []
        for _ in range(CP_PER_RACK):
            C_b[b].append(cp_id)
            cp_id += 1

    # AMR travel time from loading station to rack.
    # Values follow the instance summary PDF.
    tau_LB = {
        (0, 0): 6,
        (0, 1): 9,
        (0, 2): 12,
        (1, 0): 11,
        (1, 1): 7,
        (1, 2): 9,
    }

    # AMR return time from rack to loading station.
    tau_BL = {
        (0, 0): 6,
        (0, 1): 11,
        (1, 0): 9,
        (1, 1): 7,
        (2, 0): 12,
        (2, 1): 9,
    }

    # Handover time between AMR and rack shuttle.
    h = {b: 2 for b in B}

    # Shuttle travel and return time inside rack.
    tau_BC: dict[tuple[int, int], float] = {}
    rho: dict[tuple[int, int], float] = {}

    for b in B:
        for local_idx, c in enumerate(C_b[b]):
            shuttle_time = 7 + 2 * local_idx  # 7, 9, 11, 13 sec
            tau_BC[b, c] = shuttle_time
            rho[b, c] = shuttle_time

    # Initial availability of racks/shuttles and CPs.
    A_b = {b: 0 for b in B}
    A_c = {c: 0 for c in C}

    return B, C, C_b, tau_LB, tau_BL, tau_BC, rho, h, A_b, A_c


# ============================================================
# 3. Fixed AMR assignment
# ============================================================

def build_fixed_amr_assignment(
    P: list[int],
    a_p: dict[int, float],
) -> tuple[dict[int, int], list[tuple[int, int]], dict[int, float]]:
    """
    Fixed AMR assignment by round-robin.
    AMR assignment is not optimized in this model.
    """

    amr_of_piece = {p: p % NUM_AMR for p in P}

    K_AMR: list[tuple[int, int]] = []
    for amr in range(NUM_AMR):
        seq = [p for p in P if amr_of_piece[p] == amr]
        seq.sort()
        for i in range(len(seq) - 1):
            K_AMR.append((seq[i], seq[i + 1]))

    # Earliest start time is piece arrival/availability time.
    S0 = {p: a_p[p] for p in P}

    return amr_of_piece, K_AMR, S0


# ============================================================
# 4. Validation and summary
# ============================================================

def validate_instance(
    *,
    P: list[int],
    O: list[int],
    G: list[str],
    C: list[int],
    C_b: dict[int, list[int]],
    g_p: dict[int, str],
    d: dict[tuple[int, str], int],
) -> None:
    if len(O) > len(C):
        raise ValueError("No CP reuse: number of orders must be <= number of CPs.")

    cp_seen = [c for cp_list in C_b.values() for c in cp_list]
    if set(cp_seen) != set(C) or len(cp_seen) != len(set(cp_seen)):
        raise ValueError("Every CP must belong to exactly one rack.")

    supply = {sku: 0 for sku in G}
    for p in P:
        supply[g_p[p]] += 1

    demand = {sku: 0 for sku in G}
    for o in O:
        for sku in G:
            demand[sku] += d[o, sku]

    if supply != demand:
        raise ValueError(f"Supply-demand mismatch: supply={supply}, demand={demand}")


def print_instance_summary(
    *,
    P: list[int],
    O: list[int],
    G: list[str],
    B: list[int],
    C: list[int],
    C_b: dict[int, list[int]],
    g_p: dict[int, str],
    l_p: dict[int, int],
    a_p: dict[int, float],
    d: dict[tuple[int, str], int],
    amr_of_piece: dict[int, int],
    piece_source: dict[int, dict[str, str]],
) -> None:
    print("\n==============================")
    print("Instance Summary")
    print("==============================")
    print(f"CSV path            : {CSV_PATH}")
    print(f"CSV rows used       : {NUM_CSV_ROWS}")
    print(f"Rows per order      : {ROWS_PER_ORDER}")
    print(f"Pieces              : {len(P)}")
    print(f"Orders              : {len(O)}")
    print(f"SKUs                : {G}")
    print(f"Loading stations    : {NUM_LOADING_STATIONS}")
    print(f"AMRs                : {NUM_AMR}")
    print(f"Racks               : {len(B)}")
    print(f"CPs                 : {len(C)}")
    print("CP reuse            : No")
    print("Rack-front buffer   : No")

    print("\nRack / CP structure")
    for b in B:
        print(f"  Rack {b}: CPs {C_b[b]}")

    print("\nOrder demand")
    header = "Order | " + " | ".join(f"{sku:>16s}" for sku in G)
    print(header)
    print("-" * len(header))
    for o in O:
        row = f"{o:5d} | " + " | ".join(f"{d[o, sku]:16d}" for sku in G)
        print(row)

    print("\nPiece data")
    print("p | csv_row | SKU | LS | arrival | AMR | product")
    for p in P:
        src = piece_source[p]
        print(
            f"{p:2d} | {src['csv_row']:>7s} | {g_p[p]:16s} | "
            f"{l_p[p]:2d} | {a_p[p]:7.1f} | {amr_of_piece[p]:3d} | "
            f"{src['product_name']}"
        )

    print("\nAMR fixed sequences")
    for amr in range(NUM_AMR):
        seq = [p for p in P if amr_of_piece[p] == amr]
        seq.sort()
        print(f"  AMR {amr}: " + " -> ".join(f"P{p}" for p in seq))
