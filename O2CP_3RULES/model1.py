import gurobipy as gp
from gurobipy import GRB
import pandas as pd

# ==========================================
# 1. 인스턴스 데이터 세팅 (외부 전처리 모듈 연동)
# ==========================================
from data_loader import get_instance_data

# CSV 파일 경로
csv_file_path = "data/Online Sales Data.csv"

# 전처리 함수 호출
K, R, C, C_r, t, n, d, p, tau = get_instance_data(csv_file_path, batch_size=60)
M = 100000 

# ==========================================
# 2. Gurobi 모형 선언
# ==========================================
m = gp.Model("Model1_Nearest_Assignment")

# 결정 변수
x = m.addVars(K, C, vtype=GRB.BINARY, name="x")
y = m.addVars(K, R, vtype=GRB.BINARY, name="y")
E = m.addVars(K, vtype=GRB.CONTINUOUS, name="E")
Z = m.addVar(vtype=GRB.CONTINUOUS, name="Z")

m.setObjective(Z, GRB.MINIMIZE)

# ==========================================
# 3. 제약식 (Constraints)
# ==========================================
# (1) 용량 및 매핑 제약
m.addConstrs((gp.quicksum(x[k, c] for c in C) == 1 for k in K), name="assign_order")
m.addConstrs((gp.quicksum(x[k, c] for k in K) <= 1 for c in C), name="unique_cp")
m.addConstrs((y[k, r] == gp.quicksum(x[k, c] for c in C_r[r]) for k in K for r in R), name="map_rack")

# (2) 글로벌 최단 시간 할당 제약 (Model 1의 핵심 규칙)
m.addConstrs(
    (tau[c] * x[k, c] <= tau[c_prime] + M * gp.quicksum(x[j, c_prime] for j in range(k))
     for k in K for c in C for c_prime in C if c != c_prime),
    name="global_nearest"
)

# (3) 타임라인 제약 1: AMR의 랙 라우팅 및 셔틀 CP 할당 시간
m.addConstrs(
    (E[k] >= t[k] + gp.quicksum(d[r] * y[k, r] for r in R) + gp.quicksum((n[k] * p[c]) * x[k, c] for c in C) 
     for k in K), 
    name="timeline_amr"
)

# (4) 타임라인 제약 2: 단일 랙 셔틀 동기화
m.addConstrs(
    (E[k] >= E[j] - M * (2 - y[k, r] - y[j, r]) + gp.quicksum((n[k] * p[c]) * x[k, c] for c in C)
     for k in K for j in range(k) for r in R), 
    name="timeline_shuttle"
)

# (5) Makespan 제약
m.addConstrs((Z >= E[k] for k in K), name="makespan")

# ==========================================
# 4. 최적화 실행
# ==========================================
m.setParam('TimeLimit', 600)
m.setParam('MIPGap', 0.01)
m.optimize()

# ==========================================
# 5. 결과 확인 및 상세 스케줄 추출
# ==========================================
if m.status == GRB.OPTIMAL or m.status == GRB.TIME_LIMIT:
    print(f"\n[최적화 완료] Makespan (Z): {Z.X:.2f} 초")
    
    # 1. 랙별 총 할당량 요약
    rack_counts = {r: sum(y[k, r].X for k in K) for r in R}
    print(f"랙별 주문 할당량: {rack_counts}\n")
    
    # 2. 타임라인 추적
    schedule_data = []
    
    for k in K:
        assigned_c = [c for c in C if x[k, c].X > 0.5][0]
        assigned_r = [r for r in R if y[k, r].X > 0.5][0]
        end_time = E[k].X
        
        schedule_data.append({
            "주문 번호 (k)": k,
            "도착 시간 (t_k)": t[k],
            "작업 수량 (n_k)": n[k],
            "할당 랙 (r)": assigned_r,
            "할당 CP (c)": assigned_c,
            "완료 시간 (E_k)": round(end_time, 2)
        })
    
    # 3. Pandas DataFrame 변환
    df_schedule = pd.DataFrame(schedule_data)
    df_schedule = df_schedule.sort_values(by="도착 시간 (t_k)")
    
    # 4. 결과 출력
    print("=== 상세 분류 스케줄 타임라인 ) ===")
    print(df_schedule.head(60).to_string(index=False))
    
    # Model 1 전용 CSV로 저장
    df_schedule.to_csv("Model1_Schedule_Result.csv", index=False)

else:
    print("\n[실패] 제한 시간 내에 해를 찾지 못함.")