"""
Shared data and parameter builders for 3D sorter model instances.

Dataset version:
- Uses /data/E-Commerce DataSet.xlsx
- Expected columns:
    rec_id
    order_id
    order_date
    shipped_at
    prod_sku
    prod_qty

This file keeps the same public function signatures as the previous
instance_data.py so that horsMIP / dec_mip runners can keep importing it.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


# ============================================================
# 0. Editable experiment settings
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

CSV_CANDIDATES = [
    PROJECT_ROOT / "data" / "E-Commerce DataSet.xlsx",
    PROJECT_ROOT / "data" / "E-Commerce DataSet.csv",
    PROJECT_ROOT / "E-Commerce DataSet.xlsx",
    PROJECT_ROOT / "E-Commerce DataSet.csv",
]

CSV_PATH = next((path for path in CSV_CANDIDATES if path.exists()), CSV_CANDIDATES[0])

# ----------------------------------------------------------------
# For backward compatibility with existing runner code:
# - num_csv_rows will be interpreted as "number of selected orders"
# - rows_per_order is not used for this real order_id-based dataset
# ----------------------------------------------------------------

# Small test instance
# NUM_CSV_ROWS = 4
# MAX_TOTAL_PIECES = 40

# Medium instance: recommended next test
NUM_CSV_ROWS = 8
ROWS_PER_ORDER = 3

# Recommended dataset filtering settings
MIN_LINES_PER_ORDER = 3
MAX_LINES_PER_ORDER = 12
MAX_QTY_PER_LINE = 2
MAX_TOTAL_PIECES = 80

# System size
NUM_LOADING_STATIONS = 1
NUM_AMR = 4
NUM_RACKS = 3
CP_PER_RACK = 4

# Piece arrival interval after expanding prod_qty into individual pieces.
TIME_STEP_BETWEEN_PIECES = 2

# Solver settings
BIG_M = 10000
TIME_LIMIT = 500
MIP_GAP = 0.01
OUTPUT_FLAG = 1

# Loading station generation mode:
# - "single": all pieces use loading station 0
# - "order_hash": loading station assigned by original order_id
# - "sku_hash": loading station assigned by prod_sku
LOADING_STATION_MODE = "single"


# ============================================================
# 1. Dataset helpers
# ============================================================

def _stable_hash_mod(value: str, mod: int) -> int:
    """
    Deterministic hash modulo.

    Python's built-in hash() is randomized between sessions, so do not use it
    for reproducible instance generation.
    """
    import zlib

    if mod <= 0:
        raise ValueError("mod must be positive.")

    return zlib.crc32(value.encode("utf-8")) % mod


def _read_ecommerce_dataset(dataset_path: Path) -> pd.DataFrame:
    """Read E-Commerce DataSet from xlsx or csv."""

    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    suffix = dataset_path.suffix.lower()

    if suffix in [".xlsx", ".xls"]:
        df = pd.read_excel(dataset_path)
    elif suffix == ".csv":
        df = pd.read_csv(dataset_path)
    else:
        raise ValueError(
            f"Unsupported dataset file extension: {dataset_path.suffix}. "
            "Use .xlsx, .xls, or .csv."
        )

    # Normalize column names
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    required_columns = [
        "rec_id",
        "order_id",
        "order_date",
        "prod_sku",
        "prod_qty",
    ]

    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(
            "Dataset is missing required columns: "
            + ", ".join(missing)
            + "\nRequired columns: rec_id, order_id, order_date, prod_sku, prod_qty"
        )

    if "shipped_at" not in df.columns:
        df["shipped_at"] = ""

    return df


def _clean_ecommerce_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Clean invalid rows and add sorting columns."""

    df = df.copy()

    df["order_id"] = df["order_id"].astype(str).str.strip()
    df["prod_sku"] = df["prod_sku"].astype(str).str.strip()

    df["prod_qty"] = pd.to_numeric(df["prod_qty"], errors="coerce")
    df = df.dropna(subset=["order_id", "prod_sku", "prod_qty"])

    df = df[df["order_id"] != ""]
    df = df[df["prod_sku"] != ""]
    df = df[df["prod_qty"] > 0]

    df["prod_qty"] = df["prod_qty"].astype(int)

    # Sorting fields for piece arrival sequence
    df["order_date_parsed"] = pd.to_datetime(df["order_date"], errors="coerce")
    df["order_date_sort"] = df["order_date_parsed"].fillna(pd.Timestamp.max)

    df["rec_id_num"] = pd.to_numeric(df["rec_id"], errors="coerce")
    df["rec_id_sort"] = df["rec_id_num"].fillna(10**18)

    return df


def _select_multiline_orders(
    df: pd.DataFrame,
    *,
    num_orders: int,
    min_lines_per_order: int,
    max_lines_per_order: int,
    max_qty_per_line: int,
    max_total_pieces: int,
) -> list[str]:
    """
    Select deterministic multi-line orders.

    Selection rule:
    1. Keep orders with line count in [min_lines_per_order, max_lines_per_order].
    2. Cap each line quantity by max_qty_per_line for piece-count estimation.
    3. Sort candidate orders by earliest order_date, then earliest rec_id.
    4. Select num_orders orders without exceeding max_total_pieces.
    """

    if num_orders <= 0:
        raise ValueError("num_orders must be positive.")

    order_stats: list[dict[str, Any]] = []

    for order_id, group in df.groupby("order_id", sort=False):
        line_count = len(group)

        if line_count < min_lines_per_order:
            continue

        if line_count > max_lines_per_order:
            continue

        capped_piece_count = int(group["prod_qty"].clip(upper=max_qty_per_line).sum())

        if capped_piece_count <= 0:
            continue

        order_stats.append(
            {
                "order_id": str(order_id),
                "line_count": line_count,
                "capped_piece_count": capped_piece_count,
                "first_order_date": group["order_date_sort"].min(),
                "first_rec_id": group["rec_id_sort"].min(),
            }
        )

    if not order_stats:
        raise ValueError(
            "No multi-line candidate orders found. "
            "Try lowering MIN_LINES_PER_ORDER or increasing MAX_LINES_PER_ORDER."
        )

    stats_df = pd.DataFrame(order_stats)

    stats_df = stats_df.sort_values(
        ["first_order_date", "first_rec_id", "order_id"],
        ascending=[True, True, True],
    )

    selected: list[str] = []
    total_pieces = 0

    for _, row in stats_df.iterrows():
        order_id = str(row["order_id"])
        piece_count = int(row["capped_piece_count"])

        if total_pieces + piece_count > max_total_pieces:
            continue

        selected.append(order_id)
        total_pieces += piece_count

        if len(selected) >= num_orders:
            break

    if len(selected) < num_orders:
        raise ValueError(
            f"Only selected {len(selected)} orders, but requested {num_orders}. "
            "Try increasing MAX_TOTAL_PIECES or relaxing line-count filters."
        )

    return selected


def _assign_loading_station(original_order_id: str, sku: str) -> int:
    """Generate loading station index because the dataset has no LS column."""

    if NUM_LOADING_STATIONS <= 0:
        raise ValueError("NUM_LOADING_STATIONS must be positive.")

    if LOADING_STATION_MODE == "single":
        return 0

    if LOADING_STATION_MODE == "order_hash":
        return _stable_hash_mod(original_order_id, NUM_LOADING_STATIONS)

    if LOADING_STATION_MODE == "sku_hash":
        return _stable_hash_mod(sku, NUM_LOADING_STATIONS)

    raise ValueError(
        f"Unsupported LOADING_STATION_MODE={LOADING_STATION_MODE}. "
        "Use 'single', 'order_hash', or 'sku_hash'."
    )


# ============================================================
# 2. Dataset to piece/order data
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
    Convert E-Commerce DataSet.xlsx into model input data.

    Compatibility note:
    - This function keeps the old name and signature.
    - num_csv_rows is interpreted as the number of selected orders.
    - rows_per_order is ignored because this dataset already has real order_id.

    Rules:
    - order_id is used as the real customer order.
    - prod_sku is used as SKU.
    - prod_qty is expanded into individual pieces.
    - prod_qty is capped by MAX_QTY_PER_LINE to keep the instance small.
    - Only multi-line orders are selected.
    - Piece sequence is sorted by order_date and rec_id.
    """

    dataset_path = Path(csv_path)

    df = _read_ecommerce_dataset(dataset_path)
    df = _clean_ecommerce_dataset(df)

    num_orders = num_csv_rows

    selected_order_ids = _select_multiline_orders(
        df,
        num_orders=num_orders,
        min_lines_per_order=MIN_LINES_PER_ORDER,
        max_lines_per_order=MAX_LINES_PER_ORDER,
        max_qty_per_line=MAX_QTY_PER_LINE,
        max_total_pieces=MAX_TOTAL_PIECES,
    )

    selected_order_set = set(selected_order_ids)

    df_selected = df[df["order_id"].isin(selected_order_set)].copy()

    # Preserve selected order order from _select_multiline_orders()
    order_id_to_o = {
        order_id: idx for idx, order_id in enumerate(selected_order_ids)
    }

    O = list(range(len(selected_order_ids)))

    # Sort into piece arrival sequence.
    df_selected = df_selected.sort_values(
        ["order_date_sort", "rec_id_sort", "order_id", "prod_sku"],
        ascending=[True, True, True, True],
    )

    G = sorted(df_selected["prod_sku"].astype(str).unique().tolist())

    d: dict[tuple[int, str], int] = {(o, sku): 0 for o in O for sku in G}

    P: list[int] = []
    g_p: dict[int, str] = {}
    l_p: dict[int, int] = {}
    a_p: dict[int, float] = {}
    piece_source: dict[int, dict[str, str]] = {}

    piece_id = 0

    for _, row in df_selected.iterrows():
        original_order_id = str(row["order_id"])
        o = order_id_to_o[original_order_id]

        sku = str(row["prod_sku"])
        original_qty = int(row["prod_qty"])
        used_qty = min(original_qty, MAX_QTY_PER_LINE)

        if used_qty <= 0:
            continue

        d[o, sku] += used_qty

        loading_station = _assign_loading_station(original_order_id, sku)

        for copy_idx in range(used_qty):
            p = piece_id

            P.append(p)
            g_p[p] = sku
            l_p[p] = loading_station
            a_p[p] = float(TIME_STEP_BETWEEN_PIECES * p)

            piece_source[p] = {
                "csv_row": str(row.get("rec_id", "")),
                "rec_id": str(row.get("rec_id", "")),
                "transaction_id": original_order_id,
                "order_id": original_order_id,
                "order_index": str(o),
                "date": str(row.get("order_date", "")),
                "order_date": str(row.get("order_date", "")),
                "shipped_at": str(row.get("shipped_at", "")),
                "product_category": sku,
                "product_name": sku,
                "prod_sku": sku,
                "region": f"LS{loading_station}",
                "original_quantity": str(original_qty),
                "used_quantity": str(used_qty),
                "copy_index": str(copy_idx),
            }

            piece_id += 1

    if not P:
        raise ValueError("No pieces were generated from selected orders.")

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
# 3. Layout and time parameters from instance summary
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

    Based on the previous instance summary:
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
    # If NUM_LOADING_STATIONS = 1, only LS 0 is used.
    # If NUM_LOADING_STATIONS = 2, these match the previous instance summary.
    tau_LB: dict[tuple[int, int], float] = {}
    tau_BL: dict[tuple[int, int], float] = {}

    if NUM_LOADING_STATIONS == 1:
        for b in B:
            travel = 6 + 3 * b  # rack 0,1,2 -> 6,9,12
            tau_LB[(0, b)] = travel
            tau_BL[(b, 0)] = travel

    elif NUM_LOADING_STATIONS == 2:
        tau_LB.update(
            {
                (0, 0): 6,
                (0, 1): 9,
                (0, 2): 12,
                (1, 0): 11,
                (1, 1): 7,
                (1, 2): 9,
            }
        )

        tau_BL.update(
            {
                (0, 0): 6,
                (0, 1): 11,
                (1, 0): 9,
                (1, 1): 7,
                (2, 0): 12,
                (2, 1): 9,
            }
        )

    else:
        # Generic deterministic travel times for 3+ loading stations.
        for l in range(NUM_LOADING_STATIONS):
            for b in B:
                travel = 6 + 3 * b + 2 * abs(l - (b % NUM_LOADING_STATIONS))
                tau_LB[(l, b)] = travel
                tau_BL[(b, l)] = travel

    # Handover time between AMR and rack shuttle.
    h = {b: 2 for b in B}

    # Shuttle travel and return time inside rack.
    tau_BC: dict[tuple[int, int], float] = {}
    rho: dict[tuple[int, int], float] = {}

    for b in B:
        for local_idx, c in enumerate(C_b[b]):
            shuttle_time = 7 + 2 * local_idx  # 7, 9, 11, 13 sec
            tau_BC[(b, c)] = shuttle_time
            rho[(b, c)] = shuttle_time

    # Initial availability of racks/shuttles and CPs.
    A_b = {b: 0 for b in B}
    A_c = {c: 0 for c in C}

    return B, C, C_b, tau_LB, tau_BL, tau_BC, rho, h, A_b, A_c


# ============================================================
# 4. Fixed AMR assignment
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
# 5. Validation and summary
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
    print(f"Dataset path        : {CSV_PATH}")
    print(f"Orders selected     : {len(O)}")
    print(f"Pieces              : {len(P)}")
    print(f"Orders              : {len(O)}")
    print(f"SKUs                : {G}")
    print(f"Loading stations    : {NUM_LOADING_STATIONS}")
    print(f"AMRs                : {NUM_AMR}")
    print(f"Racks               : {len(B)}")
    print(f"CPs                 : {len(C)}")
    print("CP reuse            : No")
    print("Rack-front buffer   : No")
    print(f"Order filter        : min_lines={MIN_LINES_PER_ORDER}, max_lines={MAX_LINES_PER_ORDER}")
    print(f"Qty cap per line    : {MAX_QTY_PER_LINE}")
    print(f"Max total pieces    : {MAX_TOTAL_PIECES}")

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
    print("p | rec_id | order_id | SKU | LS | arrival | AMR | used_qty")
    for p in P:
        src = piece_source[p]

        print(
            f"{p:2d} | {src.get('rec_id', ''):>6s} | "
            f"{src.get('order_id', ''):>10s} | "
            f"{g_p[p]:16s} | "
            f"{l_p[p]:2d} | "
            f"{a_p[p]:7.1f} | "
            f"{amr_of_piece[p]:3d} | "
            f"{src.get('used_quantity', '')}"
        )

    print("\nAMR fixed sequences")
    for amr in range(NUM_AMR):
        seq = [p for p in P if amr_of_piece[p] == amr]
        seq.sort()
        print(f"  AMR {amr}: " + " -> ".join(f"P{p}" for p in seq))