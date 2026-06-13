import gurobipy as gp
from gurobipy import GRB
import pandas as pd
from data_loader import get_instance_data

# ==========================================
# 1. 인스턴스 데이터 로드 및 피스 레벨 분할
# ==========================================
csv_file_path = "data/E-Commerce DataSet.xlsx"
K, R, C, C_r, t_orders, n_orders, d, p, tau = get_instance_data(csv_file_path, batch_size=90)

# 피스 레벨 구조 생성 
P = []
P_k = {}
t_p = {}
piece_to_order = {}
piece_idx = 0
for k in K:
    P_k[k] = []
    for p_num in range(n_orders[k]):
        P.append(piece_idx)
        P_k[k].append(piece_idx)
        t_p[piece_idx] = round(piece_idx * 5.0, 2) 
        
        piece_to_order[piece_idx] = k
        piece_idx += 1

M = 100000
m = gp.Model("Model1_Piece_Level_Nearest_CP")

# ==========================================
# 2. Gurobi 변수 선언
# ==========================================
x = m.addVars(K, C, vtype=GRB.BINARY, name="x")  # 주문 k가 CP c에 할당되는가
y = m.addVars(K, R, vtype=GRB.BINARY, name="y")  # 주문 k가 랙 r에 할당되는가
E = m.addVars(P, vtype=GRB.CONTINUOUS, name="E") # 피스 i의 최종 완료 시간
Z = m.addVar(vtype=GRB.CONTINUOUS, name="Z")    # 시스템 최종 Makespan

# ==========================================
# 3. 목적함수 (Objective):
# ==========================================
# 목적은 오직 하나, 전체 완료 시간(Z)의 최소화입니다.
m.setObjective(Z, GRB.MINIMIZE)

# ==========================================
# 4. 제약식 (Constraints)
# ==========================================

# (1) 기본 할당 및 매핑 제약 (PDF 식 1, 2, 3)
m.addConstrs((gp.quicksum(x[k, c] for c in C) == 1 for k in K), name="one_cp_per_order")
m.addConstrs((gp.quicksum(x[k, c] for k in K) <= 1 for c in C), name="unique_order_per_cp")
m.addConstrs((y[k, r] == gp.quicksum(x[k, c] for c in C_r[r]) for k in K for r in R), name="rack_mapping")

# (2) 글로벌 최단 거리 규칙 제약 (Global Nearest CP Constraint)
m.addConstrs(
    (tau[c] * x[k, c] <= tau[c_prime] + M * gp.quicksum(x[j, c_prime] for j in K if j < k)
     for k in K for c in C for c_prime in C if c != c_prime),
    name="global_nearest_cp"
)

# (3) 피스 레벨 물리 타임라인 제약 1: 기본 이송 시간 (AMR + 셔틀 1회)
m.addConstrs(
    (E[i] >= t_p[i] + gp.quicksum(d[r] * y[k, r] for r in R) + gp.quicksum(p[c] * x[k, c] for c in C)
     for k in K for i in P_k[k]),
    name="piece_base_timeline"
)

# (4) 피스 레벨 물리 타임라인 제약 2: 단일 랙 내 전체 피스 순차 처리 (Shuttle Queue 간섭)
m.addConstrs(
    (E[i] >= E[j] - M * (2 - y[piece_to_order[i], r] - y[piece_to_order[j], r]) + gp.quicksum(p[c] * x[piece_to_order[i], c] for c in C)
     for i in P for j in P if j < i for r in R),
    name="shuttle_queue_interference"
)

# (5) Makespan 정의
m.addConstrs((Z >= E[i] for i in P), name="system_makespan")

# ==========================================
# 5. 솔버 세팅 및 실행
# ==========================================
m.setParam('TimeLimit', 600)
m.optimize()

# ==========================================
# 6. 결과 저장 자동화
# ==========================================
if m.status == GRB.OPTIMAL or m.status == GRB.TIME_LIMIT:
    print(f"\n[최적화 성공] Model 1 최적 Makespan (Z): {Z.X:.2f} 초")
    
    detailed_schedule = []
    for i in P:
        k = piece_to_order[i]
        assigned_c = [c for c in C if x[k, c].X > 0.5][0]
        assigned_r = [r for r in R if y[k, r].X > 0.5][0]
        
        detailed_schedule.append({
            "피스 번호 (i)": i,
            "소속 주문 번호 (k)": k,
            "피스 출발 시간 (t_i)": t_p[i],
            "할당된 랙 (r)": assigned_r,
            "할당된 CP (c)": assigned_c,
            "작업 완료 시간 (E_i)": round(E[i].X, 2)
        })
        
    df_res = pd.DataFrame(detailed_schedule)
    df_res = df_res.sort_values(by="피스 출발 시간 (t_i)")
    
    rack_summary = []
    for r in R:
        df_rack_subset = df_res[df_res["할당된 랙 (r)"] == r]
        if not df_rack_subset.empty:
            finish_time = df_rack_subset["작업 완료 시간 (E_i)"].max()
            total_pieces = len(df_rack_subset)
            unique_orders = df_rack_subset["소속 주문 번호 (k)"].nunique()
        else:
            finish_time = 0.0
            total_pieces = 0
            unique_orders = 0
            
        rack_summary.append({
            "랙 번호 (r)": r,
            "랙 최종 완료 시간 (초)": finish_time,
            "처리한 총 피스 수": total_pieces,
            "할당된 총 주문 수": unique_orders
        })
    df_racks = pd.DataFrame(rack_summary)
    
    output_filename = "Model1_Order_to_Piece_Results.xlsx"
    with pd.ExcelWriter(output_filename, engine='openpyxl') as writer:
        df_res.to_excel(writer, sheet_name="피스별 할당 타임라인", index=False)
        df_racks.to_excel(writer, sheet_name="랙별 최종 채워진 시간", index=False)
    print(f"[저장 완료] 파일명: '{output_filename}'")
else:
    print("최적해 탐색 실패")

