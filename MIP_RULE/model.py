import os
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import gurobipy as gp
from gurobipy import GRB

from data_loader import get_instance_data


# ============================================================
# 0. Utility
# ============================================================

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def safe_get_attr(model, attr_name, default=None):
    try:
        return getattr(model, attr_name)
    except Exception:
        return default


def get_var_value(var, default=0.0):
    try:
        return var.X
    except Exception:
        return default


def get_model_vars(model):
    """
    run_agv_simulation()에서 모델 객체에 저장해둔 변수 묶음을 가져온다.
    """
    return model._vars


# ============================================================
# 1. Random Assignment Generator
# ============================================================

def generate_random_assignment(K, C, seed=None):
    """
    Random CP assignment parameter Omega 생성.

    Omega[k, c] = 1 if order k is randomly assigned to CP c
                  0 otherwise

    조건:
    - 각 order는 정확히 하나의 CP에 배정
    - 각 CP는 최대 하나의 order에만 배정
    - |K| <= |C|
    """
    if len(K) > len(C):
        raise ValueError(
            f"Infeasible random assignment: number of orders ({len(K)}) "
            f"exceeds number of CPs ({len(C)})."
        )

    rng = np.random.default_rng(seed)

    selected_cps = rng.choice(C, size=len(K), replace=False)

    Omega = {(k, c): 0 for k in K for c in C}

    for k, c in zip(K, selected_cps):
        Omega[(k, int(c))] = 1

    return Omega


# ============================================================
# 2. Core Optimization Model
# ============================================================

def run_agv_simulation(
    model_type,
    sets,
    params,
    random_seed=None,
    Omega=None,
    time_limit=600,
    output_flag=1
):
    """
    model_type:
        'Model_A'      : Nearest-Time CP Assignment
        'Model_B'      : Filled-count Balancing CP Assignment
        'Model_Random' : Random CP Assignment
    """

    env = gp.Env(empty=True)
    env.setParam("OutputFlag", output_flag)
    env.start()

    m = gp.Model(f"AGV_{model_type}", env=env)

    K, I, R, C = sets["K"], sets["I"], sets["R"], sets["C"]
    C_r = sets["C_r"]
    I_k = sets["I_k"]
    k_of_i = sets["k_of_i"]

    M = params["M"]

    if len(K) > len(C):
        raise ValueError(
            f"Infeasible instance: number of orders ({len(K)}) exceeds number of CPs ({len(C)})."
        )

    # --------------------------------------------------------
    # Variables
    # --------------------------------------------------------
    x = m.addVars(K, C, vtype=GRB.BINARY, name="x")
    y = m.addVars(K, R, vtype=GRB.BINARY, name="y")

    A = m.addVars(I, vtype=GRB.CONTINUOUS, name="A")
    H = m.addVars(I, vtype=GRB.CONTINUOUS, name="H")
    W = m.addVars(I, vtype=GRB.CONTINUOUS, name="W")
    E = m.addVars(I, vtype=GRB.CONTINUOUS, name="E")
    U = m.addVars(I, vtype=GRB.CONTINUOUS, name="U")
    C_k = m.addVars(K, vtype=GRB.CONTINUOUS, name="C_k")

    # --------------------------------------------------------
    # Common assignment constraints
    # --------------------------------------------------------
    m.addConstrs(
        (gp.quicksum(x[k, c] for c in C) == 1 for k in K),
        name="assign_order"
    )

    m.addConstrs(
        (gp.quicksum(x[k, c] for k in K) <= 1 for c in C),
        name="assign_cp"
    )

    m.addConstrs(
        (
            y[k, r] == gp.quicksum(x[k, c] for c in C_r[r])
            for k in K for r in R
        ),
        name="link_cp_rack"
    )

    # --------------------------------------------------------
    # Rule-specific constraints
    # --------------------------------------------------------
    if model_type == "Model_A":
        # Model A: Global nearest-time CP rule
        for k_idx, k in enumerate(K):
            prev_orders = K[:k_idx]

            for c in C:
                for c_prime in C:
                    sum_prev_x = gp.quicksum(
                        x[k_p, c_prime] for k_p in prev_orders
                    )

                    m.addConstr(
                        params["tau"][c] * x[k, c]
                        <=
                        params["tau"][c_prime] + M * sum_prev_x,
                        name=f"nearest_global_k{k}_c{c}_cp{c_prime}"
                    )

    elif model_type == "Model_B":
        # Model B-1: Least-filled rack rule
        for k_idx, k in enumerate(K):
            prev_orders = K[:k_idx]

            for r in R:
                for r_prime in R:
                    sum_prev_y_r = gp.quicksum(
                        y[k_p, r] for k_p in prev_orders
                    )
                    sum_prev_y_rp = gp.quicksum(
                        y[k_p, r_prime] for k_p in prev_orders
                    )

                    m.addConstr(
                        sum_prev_y_r
                        <=
                        sum_prev_y_rp + M * (1 - y[k, r]),
                        name=f"least_filled_k{k}_r{r}_rp{r_prime}"
                    )

        # Model B-2: Nearest CP within selected rack
        for k_idx, k in enumerate(K):
            prev_orders = K[:k_idx]

            for r in R:
                for c in C_r[r]:
                    for c_prime in C_r[r]:
                        sum_prev_x = gp.quicksum(
                            x[k_p, c_prime] for k_p in prev_orders
                        )

                        m.addConstr(
                            params["tau"][c] * x[k, c]
                            <=
                            params["tau"][c_prime] + M * sum_prev_x,
                            name=f"nearest_within_rack_k{k}_r{r}_c{c}_cp{c_prime}"
                        )

    elif model_type == "Model_Random":
        # Random Model: x[k,c] = Omega[k,c]
        if Omega is None:
            Omega = generate_random_assignment(K, C, seed=random_seed)

        m._Omega = Omega
        m._random_seed = random_seed

        for k in K:
            for c in C:
                m.addConstr(
                    x[k, c] == Omega[(k, c)],
                    name=f"random_assign_k{k}_c{c}"
                )

    else:
        raise ValueError(
            "Unknown model_type. Use 'Model_A', 'Model_B', or 'Model_Random'."
        )

    # --------------------------------------------------------
    # Piece-level timing constraints
    # --------------------------------------------------------
    for i_idx, i in enumerate(I):
        k_i = k_of_i[i]

        m.addConstr(
            A[i] == params["a"][i]
            + gp.quicksum(params["d"][r] * y[k_i, r] for r in R),
            name=f"amr_arrival_i{i}"
        )

        m.addConstr(
            H[i] >= A[i],
            name=f"handover_after_arrival_i{i}"
        )

        m.addConstr(
            W[i] == H[i] - A[i],
            name=f"waiting_time_i{i}"
        )

        m.addConstr(
            E[i] == H[i] + params["h"]
            + gp.quicksum(params["q"][c] * x[k_i, c] for c in C),
            name=f"piece_completion_i{i}"
        )

        m.addConstr(
            U[i] == H[i] + params["h"]
            + gp.quicksum(params["p"][c] * x[k_i, c] for c in C),
            name=f"shuttle_release_i{i}"
        )

        # same-rack shuttle sequence constraints
        for j_idx in range(i_idx):
            j = I[j_idx]
            k_j = k_of_i[j]

            for r in R:
                m.addConstr(
                    H[i] >= U[j] - M * (2 - y[k_i, r] - y[k_j, r]),
                    name=f"shuttle_sequence_j{j}_i{i}_r{r}"
                )

    # --------------------------------------------------------
    # Order completion time
    # --------------------------------------------------------
    m.addConstrs(
        (
            C_k[k] >= E[i]
            for k in K
            for i in I_k[k]
        ),
        name="OrderEnd"
    )

    # --------------------------------------------------------
    # Objective
    # --------------------------------------------------------
    obj = (
        gp.quicksum(C_k[k] for k in K)
    )

    m.setObjective(obj, GRB.MINIMIZE)

    m.setParam("TimeLimit", time_limit)

    # Optional: reduce numerical noise
    m.setParam("MIPGap", 0.0001)

    m.optimize()

    # Store variables for analysis
    m._vars = {
        "x": x,
        "y": y,
        "A": A,
        "H": H,
        "W": W,
        "E": E,
        "U": U,
        "C_k": C_k
    }
    m._sets = sets
    m._params = params
    m._model_type = model_type

    if m.SolCount > 0:
        print(
            f"[{model_type}] Feasible solution found. "
            f"Obj Val: {m.ObjVal:.4f}, Status: {m.status}, Runtime: {m.Runtime:.2f}s"
        )
        return m
    else:
        print(f"[{model_type}] No feasible solution found. Status: {m.status}")
        return None


# ============================================================
# 3. KPI Extraction
# ============================================================

def get_assigned_cp_and_rack(model, sets, k):
    vars_ = get_model_vars(model)
    x = vars_["x"]
    y = vars_["y"]

    C = sets["C"]
    R = sets["R"]

    assigned_cp = None
    assigned_rack = None

    for c in C:
        if get_var_value(x[k, c]) > 0.5:
            assigned_cp = c
            break

    for r in R:
        if get_var_value(y[k, r]) > 0.5:
            assigned_rack = r
            break

    return assigned_cp, assigned_rack


def extract_kpis_custom(model, sets, label, seed=None):
    vars_ = get_model_vars(model)

    K = sets["K"]
    I = sets["I"]
    R = sets["R"]
    k_of_i = sets["k_of_i"]

    y = vars_["y"]
    W = vars_["W"]
    C_k = vars_["C_k"]

    order_completion = np.array([get_var_value(C_k[k]) for k in K], dtype=float)
    waits = np.array([get_var_value(W[i]) for i in I], dtype=float)

    rack_order_counts = {r: 0 for r in R}
    rack_piece_counts = {r: 0 for r in R}
    rack_wait_sum = {r: 0.0 for r in R}

    for k in K:
        _, r = get_assigned_cp_and_rack(model, sets, k)
        if r is not None:
            rack_order_counts[r] += 1

    for i in I:
        k = k_of_i[i]
        _, r = get_assigned_cp_and_rack(model, sets, k)
        if r is not None:
            rack_piece_counts[r] += 1
            rack_wait_sum[r] += get_var_value(W[i])

    rack_order_values = np.array(list(rack_order_counts.values()), dtype=float)
    rack_piece_values = np.array(list(rack_piece_counts.values()), dtype=float)
    rack_wait_values = np.array(list(rack_wait_sum.values()), dtype=float)

    try:
        mip_gap = model.MIPGap
    except Exception:
        mip_gap = np.nan

    record = {
        "policy": label,
        "seed": seed,
        "status": model.status,
        "runtime": model.Runtime,
        "mip_gap": mip_gap,
        "objective": model.ObjVal,
        "sum_order_completion": float(np.sum(order_completion)),
        "sum_wait": float(np.sum(waits)),
        "avg_order_completion": float(np.mean(order_completion)) if len(order_completion) else 0.0,
        "max_order_completion": float(np.max(order_completion)) if len(order_completion) else 0.0,
        "avg_wait": float(np.mean(waits)) if len(waits) else 0.0,
        "max_wait": float(np.max(waits)) if len(waits) else 0.0,
        "used_racks": int(np.sum(rack_order_values > 0)),
        "rack_order_std": float(np.std(rack_order_values)),
        "rack_piece_std": float(np.std(rack_piece_values)),
        "rack_wait_std": float(np.std(rack_wait_values)),
    }

    for r in R:
        record[f"rack_{r}_order_count"] = rack_order_counts[r]
        record[f"rack_{r}_piece_count"] = rack_piece_counts[r]
        record[f"rack_{r}_wait_sum"] = rack_wait_sum[r]

    return record


# ============================================================
# 4. Detail Export
# ============================================================

def build_piece_details_df(model, sets, params, label):
    vars_ = get_model_vars(model)

    K = sets["K"]
    I = sets["I"]
    k_of_i = sets["k_of_i"]

    A = vars_["A"]
    H = vars_["H"]
    W = vars_["W"]
    E = vars_["E"]
    U = vars_["U"]
    C_k = vars_["C_k"]

    rows = []

    for i in I:
        k = k_of_i[i]
        assigned_cp, assigned_rack = get_assigned_cp_and_rack(model, sets, k)

        original_order_id = None
        if "k_to_order_id" in sets:
            original_order_id = sets["k_to_order_id"].get(k)

        source_row = None
        if "piece_info" in sets and i in sets["piece_info"]:
            source_row = sets["piece_info"][i].get("source_row")

        rows.append({
            "policy": label,
            "piece_i": i,
            "order_k": k,
            "original_order_id": original_order_id,
            "source_row": source_row,
            "assigned_cp": assigned_cp,
            "assigned_rack": assigned_rack,
            "release_a_i": params["a"][i],
            "AMR_arrival_A_i": get_var_value(A[i]),
            "handover_start_H_i": get_var_value(H[i]),
            "AMR_wait_W_i": get_var_value(W[i]),
            "piece_completion_E_i": get_var_value(E[i]),
            "shuttle_release_U_i": get_var_value(U[i]),
            "order_completion_C_k": get_var_value(C_k[k]),
        })

    return pd.DataFrame(rows)


def export_piece_details(model, sets, params, label, output_path):
    df = build_piece_details_df(model, sets, params, label)
    df.to_excel(output_path, index=False)
    print(f"[Saved] {output_path}")
    return df


def export_multi_piece_details(models_info, sets, params, output_path):
    """
    models_info: list of (label, model)
    """
    all_rows = []

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for label, model in models_info:
            df = build_piece_details_df(model, sets, params, label)
            sheet_name = label[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            all_rows.append(df)

        combined = pd.concat(all_rows, ignore_index=True)
        combined.to_excel(writer, sheet_name="combined", index=False)

    print(f"[Saved] {output_path}")


# ============================================================
# 5. Visualization
# ============================================================

def plot_objective_comparison(comparison_df, output_path):
    labels = comparison_df["Policy"].tolist()
    values = comparison_df["Objective"].tolist()

    plt.figure(figsize=(10, 6))
    plt.bar(labels, values)
    plt.ylabel("Objective Value")
    plt.title("Objective Comparison")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()
    print(f"[Saved] {output_path}")


def plot_random_objective_histogram(random_df, output_path):
    plt.figure(figsize=(10, 6))
    plt.hist(random_df["objective"], bins=10)
    plt.xlabel("Objective Value")
    plt.ylabel("Frequency")
    plt.title("Random Policy Objective Distribution")
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()
    print(f"[Saved] {output_path}")


def plot_cumulative_wait(models_info, sets, output_path):
    I = sets["I"]

    plt.figure(figsize=(10, 6))

    for label, model in models_info:
        W = get_model_vars(model)["W"]
        waits = [get_var_value(W[i]) for i in I]
        cum_wait = np.cumsum(waits)
        plt.plot(range(len(I)), cum_wait, label=label)

    plt.xlabel("Piece sequence")
    plt.ylabel("Cumulative AMR waiting time")
    plt.title("Cumulative AMR Waiting Time")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()
    print(f"[Saved] {output_path}")


def plot_gantt_single(model, sets, label, output_path):
    I = sets["I"]
    R = sets["R"]
    k_of_i = sets["k_of_i"]

    vars_ = get_model_vars(model)
    H = vars_["H"]
    U = vars_["U"]

    plt.figure(figsize=(12, 6))

    for i in I:
        k = k_of_i[i]
        _, r = get_assigned_cp_and_rack(model, sets, k)

        if r is None:
            continue

        h_val = get_var_value(H[i])
        u_val = get_var_value(U[i])
        duration = max(0.0, u_val - h_val)

        plt.broken_barh(
            [(h_val, duration)],
            (r - 0.4, 0.8)
        )

    plt.xlabel("Time")
    plt.ylabel("Rack")
    plt.yticks(R)
    plt.title(f"Gantt Chart - {label}")
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()
    print(f"[Saved] {output_path}")


def plot_cp_heatmap_single(model, sets, label, output_path):
    R = sets["R"]
    C_r = sets["C_r"]
    K = sets["K"]

    max_cps_per_rack = max(len(C_r[r]) for r in R)
    heat = np.full((len(R), max_cps_per_rack), np.nan)

    for r_idx, r in enumerate(R):
        for local_idx, c in enumerate(C_r[r]):
            heat[r_idx, local_idx] = 0

    for k in K:
        cp, rack = get_assigned_cp_and_rack(model, sets, k)
        if cp is None or rack is None:
            continue

        local_idx = C_r[rack].index(cp)
        rack_idx = R.index(rack)
        heat[rack_idx, local_idx] = 1

    plt.figure(figsize=(12, 5))
    plt.imshow(heat, aspect="auto")
    plt.colorbar(label="CP used")
    plt.xlabel("CP position within rack")
    plt.ylabel("Rack")
    plt.yticks(range(len(R)), R)
    plt.title(f"CP Usage Heatmap - {label}")
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()
    print(f"[Saved] {output_path}")


# ============================================================
# 6. Random Experiment Runner
# ============================================================

def run_random_experiments(
    sets,
    params,
    seeds,
    time_limit=600,
    output_flag=0
):
    random_records = []
    random_models = {}

    for seed in seeds:
        print(f"\n--- Model Random 실행: seed={seed} ---")

        model_random = run_agv_simulation(
            "Model_Random",
            sets,
            params,
            random_seed=seed,
            time_limit=time_limit,
            output_flag=output_flag
        )

        if model_random is not None and model_random.SolCount > 0:
            label = f"Random_seed_{seed}"
            kpi = extract_kpis_custom(model_random, sets, label, seed=seed)
            random_records.append(kpi)
            random_models[seed] = model_random

    if not random_records:
        raise RuntimeError("No feasible random solutions found.")

    random_df = pd.DataFrame(random_records)

    return random_df, random_models


def summarize_random_results(random_df):
    metrics = [
        "objective",
        "sum_order_completion",
        "sum_wait",
        "avg_order_completion",
        "max_order_completion",
        "avg_wait",
        "max_wait",
        "used_racks",
        "rack_order_std",
        "rack_piece_std",
        "rack_wait_std"
    ]

    summary_rows = []

    for metric in metrics:
        values = random_df[metric].dropna()
        summary_rows.append({
            "metric": metric,
            "mean": values.mean(),
            "std": values.std(),
            "min": values.min(),
            "median": values.median(),
            "max": values.max()
        })

    return pd.DataFrame(summary_rows)


def select_representative_random_seeds(random_df):
    best_seed = int(random_df.loc[random_df["objective"].idxmin(), "seed"])
    worst_seed = int(random_df.loc[random_df["objective"].idxmax(), "seed"])

    median_obj = random_df["objective"].median()
    median_idx = (random_df["objective"] - median_obj).abs().idxmin()
    median_seed = int(random_df.loc[median_idx, "seed"])

    return best_seed, median_seed, worst_seed


# ============================================================
# 7. Final Result Export
# ============================================================

def build_final_comparison_table(kpi_A, kpi_B, random_df):
    best_row = random_df.loc[random_df["objective"].idxmin()]
    worst_row = random_df.loc[random_df["objective"].idxmax()]

    def row_from_kpi(policy_name, kpi, note):
        return {
            "Policy": policy_name,
            "Objective": kpi["objective"],
            "Sum_Ck": kpi["sum_order_completion"],
            "Sum_Wi": kpi["sum_wait"],
            "Avg_Ck": kpi["avg_order_completion"],
            "Max_Ck": kpi["max_order_completion"],
            "Avg_Wi": kpi["avg_wait"],
            "Max_Wi": kpi["max_wait"],
            "Used_Racks": kpi["used_racks"],
            "Rack_Order_Std": kpi["rack_order_std"],
            "Rack_Piece_Std": kpi["rack_piece_std"],
            "Note": note
        }

    rows = []

    rows.append(row_from_kpi("Model A", kpi_A, "deterministic"))
    rows.append(row_from_kpi("Model B", kpi_B, "deterministic"))

    rows.append({
        "Policy": "Random Avg.",
        "Objective": random_df["objective"].mean(),
        "Sum_Ck": random_df["sum_order_completion"].mean(),
        "Sum_Wi": random_df["sum_wait"].mean(),
        "Avg_Ck": random_df["avg_order_completion"].mean(),
        "Max_Ck": random_df["max_order_completion"].mean(),
        "Avg_Wi": random_df["avg_wait"].mean(),
        "Max_Wi": random_df["max_wait"].mean(),
        "Used_Racks": random_df["used_racks"].mean(),
        "Rack_Order_Std": random_df["rack_order_std"].mean(),
        "Rack_Piece_Std": random_df["rack_piece_std"].mean(),
        "Note": f"mean over {len(random_df)} seeds"
    })

    rows.append({
        "Policy": "Random Best",
        "Objective": best_row["objective"],
        "Sum_Ck": best_row["sum_order_completion"],
        "Sum_Wi": best_row["sum_wait"],
        "Avg_Ck": best_row["avg_order_completion"],
        "Max_Ck": best_row["max_order_completion"],
        "Avg_Wi": best_row["avg_wait"],
        "Max_Wi": best_row["max_wait"],
        "Used_Racks": best_row["used_racks"],
        "Rack_Order_Std": best_row["rack_order_std"],
        "Rack_Piece_Std": best_row["rack_piece_std"],
        "Note": f"best seed={int(best_row['seed'])}"
    })

    rows.append({
        "Policy": "Random Worst",
        "Objective": worst_row["objective"],
        "Sum_Ck": worst_row["sum_order_completion"],
        "Sum_Wi": worst_row["sum_wait"],
        "Avg_Ck": worst_row["avg_order_completion"],
        "Max_Ck": worst_row["max_order_completion"],
        "Avg_Wi": worst_row["avg_wait"],
        "Max_Wi": worst_row["max_wait"],
        "Used_Racks": worst_row["used_racks"],
        "Rack_Order_Std": worst_row["rack_order_std"],
        "Rack_Piece_Std": worst_row["rack_piece_std"],
        "Note": f"worst seed={int(worst_row['seed'])}"
    })

    return pd.DataFrame(rows)


def export_summary_excel(
    output_path,
    comparison_df,
    random_df,
    random_summary_df,
    kpi_A,
    kpi_B,
    kpi_R_best,
    kpi_R_median,
    kpi_R_worst
):
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        comparison_df.to_excel(writer, sheet_name="comparison", index=False)
        random_df.to_excel(writer, sheet_name="random_runs", index=False)
        random_summary_df.to_excel(writer, sheet_name="random_summary", index=False)

        pd.DataFrame([kpi_A]).to_excel(writer, sheet_name="model_A_kpi", index=False)
        pd.DataFrame([kpi_B]).to_excel(writer, sheet_name="model_B_kpi", index=False)
        pd.DataFrame([kpi_R_best]).to_excel(writer, sheet_name="random_best_kpi", index=False)
        pd.DataFrame([kpi_R_median]).to_excel(writer, sheet_name="random_median_kpi", index=False)
        pd.DataFrame([kpi_R_worst]).to_excel(writer, sheet_name="random_worst_kpi", index=False)

    print(f"[Saved] {output_path}")


# ============================================================
# 8. Main
# ============================================================

if __name__ == "__main__":
    # --------------------------------------------------------
    # User settings
    # --------------------------------------------------------
    CSV_PATH = "C:/Users/mstot/3D_sorting_system/MIP_RULE/data/E-Commerce DataSet.xlsx"

    BATCH_SIZE = 90
    TIME_LIMIT_AB = 600
    TIME_LIMIT_RANDOM = 600

    # Random seed 개수.
    # 시간이 너무 오래 걸리면 list(range(10))으로 줄여도 됨.
    RANDOM_SEEDS = list(range(30))

    RESULTS_DIR = "results"
    FIGURE_DIR = os.path.join(RESULTS_DIR, "figures")

    ensure_dir(RESULTS_DIR)
    ensure_dir(FIGURE_DIR)

    # --------------------------------------------------------
    # Load data
    # --------------------------------------------------------
    print("데이터를 전처리 중입니다...")
    sets, params = get_instance_data(CSV_PATH, batch_size=BATCH_SIZE)

    print(f"총 Order 수: {len(sets['K'])}")
    print(f"총 Piece 수: {len(sets['I'])}")
    print(f"총 Rack 수: {len(sets['R'])}")
    print(f"총 CP 수: {len(sets['C'])}")

    if len(sets["K"]) > len(sets["C"]):
        raise ValueError(
            f"Infeasible instance: number of orders ({len(sets['K'])}) "
            f"exceeds number of CPs ({len(sets['C'])})."
        )

    # --------------------------------------------------------
    # Run deterministic policies
    # --------------------------------------------------------
    print("\n--- Model A 실행: Nearest-Time CP Assignment ---")
    model_A = run_agv_simulation(
        "Model_A",
        sets,
        params,
        time_limit=TIME_LIMIT_AB,
        output_flag=1
    )

    print("\n--- Model B 실행: Filled-count Balancing CP Assignment ---")
    model_B = run_agv_simulation(
        "Model_B",
        sets,
        params,
        time_limit=TIME_LIMIT_AB,
        output_flag=1
    )

    if model_A is None or model_B is None:
        raise RuntimeError("Model A 또는 Model B에서 feasible solution을 찾지 못했습니다.")

    kpi_A = extract_kpis_custom(model_A, sets, "Model A")
    kpi_B = extract_kpis_custom(model_B, sets, "Model B")

    # --------------------------------------------------------
    # Run random experiments
    # --------------------------------------------------------
    print("\n--- Random Policy 반복 실험 시작 ---")
    random_df, random_models = run_random_experiments(
        sets,
        params,
        seeds=RANDOM_SEEDS,
        time_limit=TIME_LIMIT_RANDOM,
        output_flag=0
    )

    random_summary_df = summarize_random_results(random_df)

    best_seed, median_seed, worst_seed = select_representative_random_seeds(random_df)

    random_best_model = random_models[best_seed]
    random_median_model = random_models[median_seed]
    random_worst_model = random_models[worst_seed]

    kpi_R_best = extract_kpis_custom(
        random_best_model,
        sets,
        "Random Best",
        seed=best_seed
    )
    kpi_R_median = extract_kpis_custom(
        random_median_model,
        sets,
        "Random Median",
        seed=median_seed
    )
    kpi_R_worst = extract_kpis_custom(
        random_worst_model,
        sets,
        "Random Worst",
        seed=worst_seed
    )

    # --------------------------------------------------------
    # Save KPI files
    # --------------------------------------------------------
    random_runs_path = os.path.join(RESULTS_DIR, "random_runs_kpi.csv")
    random_summary_path = os.path.join(RESULTS_DIR, "random_summary.csv")

    random_df.to_csv(random_runs_path, index=False, encoding="utf-8-sig")
    random_summary_df.to_csv(random_summary_path, index=False, encoding="utf-8-sig")

    print(f"[Saved] {random_runs_path}")
    print(f"[Saved] {random_summary_path}")

    comparison_df = build_final_comparison_table(kpi_A, kpi_B, random_df)

    summary_excel_path = os.path.join(RESULTS_DIR, "summary_comparison.xlsx")
    export_summary_excel(
        summary_excel_path,
        comparison_df,
        random_df,
        random_summary_df,
        kpi_A,
        kpi_B,
        kpi_R_best,
        kpi_R_median,
        kpi_R_worst
    )

    # --------------------------------------------------------
    # Save piece details
    # --------------------------------------------------------
    export_piece_details(
        model_A,
        sets,
        params,
        "Model A",
        os.path.join(RESULTS_DIR, "model_A_piece_details.xlsx")
    )

    export_piece_details(
        model_B,
        sets,
        params,
        "Model B",
        os.path.join(RESULTS_DIR, "model_B_piece_details.xlsx")
    )

    export_piece_details(
        random_best_model,
        sets,
        params,
        f"Random Best seed={best_seed}",
        os.path.join(RESULTS_DIR, "random_best_piece_details.xlsx")
    )

    export_piece_details(
        random_median_model,
        sets,
        params,
        f"Random Median seed={median_seed}",
        os.path.join(RESULTS_DIR, "random_median_piece_details.xlsx")
    )

    export_piece_details(
        random_worst_model,
        sets,
        params,
        f"Random Worst seed={worst_seed}",
        os.path.join(RESULTS_DIR, "random_worst_piece_details.xlsx")
    )

    export_multi_piece_details(
        [
            ("Model A", model_A),
            ("Model B", model_B),
            (f"Random Best seed={best_seed}", random_best_model),
            (f"Random Median seed={median_seed}", random_median_model),
            (f"Random Worst seed={worst_seed}", random_worst_model),
        ],
        sets,
        params,
        os.path.join(RESULTS_DIR, "representative_piece_details.xlsx")
    )

    # --------------------------------------------------------
    # Save figures
    # --------------------------------------------------------
    plot_objective_comparison(
        comparison_df,
        os.path.join(FIGURE_DIR, "objective_comparison.png")
    )

    plot_random_objective_histogram(
        random_df,
        os.path.join(FIGURE_DIR, "random_objective_histogram.png")
    )

    plot_cumulative_wait(
        [
            ("Model A", model_A),
            ("Model B", model_B),
            (f"Random Best seed={best_seed}", random_best_model),
        ],
        sets,
        os.path.join(FIGURE_DIR, "cumulative_wait_comparison.png")
    )

    plot_gantt_single(
        model_A,
        sets,
        "Model A",
        os.path.join(FIGURE_DIR, "gantt_Model_A.png")
    )

    plot_gantt_single(
        model_B,
        sets,
        "Model B",
        os.path.join(FIGURE_DIR, "gantt_Model_B.png")
    )

    plot_gantt_single(
        random_best_model,
        sets,
        f"Random Best seed={best_seed}",
        os.path.join(FIGURE_DIR, "gantt_Random_Best.png")
    )

    plot_cp_heatmap_single(
        model_A,
        sets,
        "Model A",
        os.path.join(FIGURE_DIR, "cp_heatmap_Model_A.png")
    )

    plot_cp_heatmap_single(
        model_B,
        sets,
        "Model B",
        os.path.join(FIGURE_DIR, "cp_heatmap_Model_B.png")
    )

    plot_cp_heatmap_single(
        random_best_model,
        sets,
        f"Random Best seed={best_seed}",
        os.path.join(FIGURE_DIR, "cp_heatmap_Random_Best.png")
    )

    # --------------------------------------------------------
    # Console summary
    # --------------------------------------------------------
    print("\n========== Final Summary ==========")
    print(comparison_df.to_string(index=False))

    print("\n========== Random Representative Seeds ==========")
    print(f"Best random seed   : {best_seed}")
    print(f"Median random seed : {median_seed}")
    print(f"Worst random seed  : {worst_seed}")

    print("\n모든 결과 저장이 완료되었습니다.")
    print(f"결과 폴더: {os.path.abspath(RESULTS_DIR)}")