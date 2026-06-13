# model3.py
import gurobipy as gp
from gurobipy import GRB
import pandas as pd
from data_loader import get_instance_data

# ==========================================
# 1. 인스턴스 데이터 로드 및 Piece-level 계층 구조 생성
# ==========================================
csv_file_path = "data/E-Commerce DataSet.xlsx"

# [데이터 로드] 수정된 data_loader.py로부터 물리 제원이 반영된 파라미터 수신
K, R, C, C_r, t_orders, n_orders, d, p, tau = get_instance_data(csv_file_path, batch_size=90)

# 피스 레벨 데이터 매핑 구조 빌드
P = []                 # 전체 피스 ID 리스트
P_k = {}               # 주문별 속한 피스들의 ID 리스트 {k: [i1, i2, ...]}
t_p = {}               # 피스별 고유 출발 타임스탬프 파라미터 (t_i)
piece_to_order = {}   # 피스 ID를 통해 역으로 오더 ID를 찾기 위한 딕셔너리

piece_idx = 0
for k in K:
    num_pieces = n_orders[k]
    base_t = t_orders[k]  # data_loader에서 넘어온 t_orders 매핑
    P_k[k] = []
    for p_num in range(num_pieces):
        P.append(piece_idx)
        P_k[k].append(piece_idx)
        t_p[piece_idx] = round(base_t + p_num * 5, 2)
        piece_to_order[piece_idx] = k
        piece_idx += 1

# 솔버의 계산 효율을 높이기 위해 Big-M 값을 현실적인 최대 시간 범위로 조정
M = 2000  

# ==========================================
# 2. Gurobi 모형 및 변수 선언
# ==========================================
m = gp.Model("Model3_Order_to_Piece_Balancing")

# [결정 변수]: 주문(k) 기준 할당 정의 (1개 CP에는 최대 1개 주문만 할당)
x = m.addVars(K, C, vtype=GRB.BINARY, name="x")  # 주문 k가 CP c에 할당되는가
y = m.addVars(K, R, vtype=GRB.BINARY, name="y")  # 주문 k가 랙 r에 할당되는가

# [평가 변수]: 피스(i) 기준 타임라인 정의
E = m.addVars(P, vtype=GRB.CONTINUOUS, name="E") # 피스 i의 최종 완료 시간
Z = m.addVar(vtype=GRB.CONTINUOUS, name="Z")    # 시스템 최종 Makespan

# 목적함수 설정: 최종 피스 완료 시간(Makespan)의 최소화
m.setObjective(Z, GRB.MINIMIZE)

# ==========================================
# 3. 제약식 (Constraints) 구현
# ==========================================

# (1) 주문 대 CP 1:1 매칭 제약
m.addConstrs((gp.quicksum(x[k, c] for c in C) == 1 for k in K), name="one_cp_per_order")
m.addConstrs((gp.quicksum(x[k, c] for k in K) <= 1 for c in C), name="unique_order_per_cp")
m.addConstrs((y[k, r] == gp.quicksum(x[k, c] for c in C_r[r]) for k in K for r in R), name="rack_mapping")

# (2) Model 3: 누적 할당 기반 워크로드 균형 제약 (piece 레벨 단계적 제어)
m.addConstrs(
    (gp.quicksum(n_orders[j] * y[j, r] for j in K if j < k) <= gp.quicksum(n_orders[j] * y[j, r_prime] for j in K if j < k) + M * (1 - y[k, r])
     for k in K for r in R for r_prime in R if r != r_prime),
    name="true_piece_workload_balance"
)

# (3) 랙 내부 최단 거리 CP 선택 제약 (Local Nearest Tie-breaker)
m.addConstrs(
    (tau[c] * x[k, c] <= tau[c_prime] + M * gp.quicksum(x[j, c_prime] for j in K if j < k)
     for k in K for r in R for c in C_r[r] for c_prime in C_r[r] if c != c_prime),
    name="local_nearest_cp"
)

# (4) 피스 레벨 물리 타임라인 제약 1: AMR 및 tSort3D 3D 물리 제원 기반 기본 가동 시간
m.addConstrs(
    (E[i] >= t_p[i] + gp.quicksum(d[r] * y[k, r] for r in R) + gp.quicksum(p[c] * x[k, c] for c in C)
     for k in K for i in P_k[k]),
    name="piece_base_timeline"
)

# (5) 피스 레벨 물리 타임라인 제약 2: 단일 랙 내 전체 피스 순차 처리 (Shuttle Queue 동기화)
m.addConstrs(
    (E[i] >= E[j] - M * (2 - y[piece_to_order[i], r] - y[piece_to_order[j], r]) + gp.quicksum(p[c] * x[piece_to_order[i], c] for c in C)
     for i in P for j in P if j < i for r in R),
    name="shuttle_queue_interference"
)

# (6) Makespan 제약
m.addConstrs((Z >= E[i] for i in P), name="system_makespan")

# ==========================================
# 4. 솔버 세팅 및 최적화 실행
# ==========================================
m.setParam('TimeLimit', 600)  # 최대 10분 연산 부하 제한
m.setParam('MIPGap', 0.00)     # 1% 이내 갭 수렴 시 종료
m.optimize()

# ==========================================
# 5. 결과 저장 및 엑셀 출력 자동화
# ==========================================
if m.status == GRB.OPTIMAL or m.status == GRB.TIME_LIMIT:
    print(f"\n[최적화 성공] 최종 피스 단위 최적 Makespan (Z): {Z.X:.2f} 초")
    
    # 데이터 조립을 위한 리스트
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
    
    # 랙별 최종 피스 완료 시간 요약집 연산
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
    
    # 다중 시트 엑셀 파일 저장
    output_filename = "Model3_Order_to_Piece_Results.xlsx"
    with pd.ExcelWriter(output_filename, engine='openpyxl') as writer:
        df_res.to_excel(writer, sheet_name="피스별 할당 타임라인", index=False)
        df_racks.to_excel(writer, sheet_name="랙별 최종 채워진 시간", index=False)
        
    print(f"[저장 완료] 엑셀 파일 '{output_filename}'이 성공적으로 생성되었습니다.")
else:
    print("최적 해를 찾는 데 실패했거나 제한 시간을 초과했습니다.")

