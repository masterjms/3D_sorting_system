import gurobipy as gp
from gurobipy import GRB

# ==========================================
# 1. 인스턴스 데이터 세팅 (외부 전처리 모듈 연동)
# ==========================================
# 새롭게 구성한 data_loader에서 데이터를 한 번에 불러옵니다.
from data_loader import get_instance_data

# CSV 파일 경로 (현재 프로젝트 폴더 구조에 맞춤)
csv_file_path = "data/Online Sales Data.csv"

# 전처리 함수 호출하여 파라미터들 받아오기
# t: 초 단위 도착 시간, n: 주문별 피스 수량(Units Sold)
K, R, C, C_r, t, n, d, p, tau = get_instance_data(csv_file_path, batch_size=60)

M = 100000  # Big-M

# ==========================================
# 2. Gurobi 모형 및 변수 선언
# ==========================================
m = gp.Model("Model3_Hierarchical_Balancing")

# 결정 변수
x = m.addVars(K, C, vtype=GRB.BINARY, name="x")
y = m.addVars(K, R, vtype=GRB.BINARY, name="y")

# 평가 변수
E = m.addVars(K, vtype=GRB.CONTINUOUS, name="E")
Z = m.addVar(vtype=GRB.CONTINUOUS, name="Z")

# 목적함수
m.setObjective(Z, GRB.MINIMIZE)

# ==========================================
# 3. 제약식 (Constraints)
# ==========================================
# (1) 용량 및 매핑 제약
m.addConstrs((gp.quicksum(x[k, c] for c in C) == 1 for k in K), name="assign_order")
m.addConstrs((gp.quicksum(x[k, c] for k in K) <= 1 for c in C), name="unique_cp")
m.addConstrs((y[k, r] == gp.quicksum(x[k, c] for c in C_r[r]) for k in K for r in R), name="map_rack")

# (2) 랙 단위 누적 워크로드 밸런싱 제약
m.addConstrs(
    (gp.quicksum(y[j, r] for j in range(k)) <= gp.quicksum(y[j, r_prime] for j in range(k)) + M * (1 - y[k, r])
     for k in K for r in R for r_prime in R if r != r_prime),
    name="workload_balance"
)

# (3) 선택된 랙 내부 최단 시간(tau) 제약 (Local Tie-breaker)
m.addConstrs(
    (tau[c] * x[k, c] <= tau[c_prime] + M * gp.quicksum(x[j, c_prime] for j in range(k))
     for k in K for r in R for c in C_r[r] for c_prime in C_r[r] if c != c_prime),
    name="local_nearest"
)

# (4) 타임라인 제약 1: AMR의 랙 라우팅 및 셔틀 CP 할당 시간 반영
m.addConstrs(
    (E[k] >= t[k] + gp.quicksum(d[r] * y[k, r] for r in R) + gp.quicksum((n[k] * p[c]) * x[k, c] for c in C) 
     for k in K), 
    name="timeline_amr"
)

# (5) 타임라인 제약 2: 단일 랙 셔틀 동기화 (Single Machine Scheduling)
m.addConstrs(
    (E[k] >= E[j] - M * (2 - y[k, r] - y[j, r]) + gp.quicksum((n[k] * p[c]) * x[k, c] for c in C)
     for k in K for j in range(k) for r in R), 
    name="timeline_shuttle"
)

# (6) Makespan 제약
m.addConstrs((Z >= E[k] for k in K), name="makespan")

# ==========================================
# 4. 솔버 세팅 및 최적화 실행
# ==========================================
m.setParam('TimeLimit', 600)  # 연산 시간 제한 (10분)
m.setParam('MIPGap', 0.01)    # 1% 이내 갭 도달 시 종료
m.optimize()

# ==========================================
# 5. 결과 확인 및 상세 스케줄 추출
# ==========================================
import pandas as pd

if m.status == GRB.OPTIMAL or m.status == GRB.TIME_LIMIT:
    print(f"\n[최적화 완료] Makespan (Z): {Z.X:.2f} 초")
    
    # 1. 랙별 총 할당량 요약
    rack_counts = {r: sum(y[k, r].X for k in K) for r in R}
    print(f"랙별 주문 할당량: {rack_counts}\n")
    
    # 2. 1번 피스부터 60번 피스까지의 타임라인 추적
    schedule_data = []
    
    for k in K:
        # Gurobi 변수(.X)에서 값이 1.0(즉, 선택됨)인 CP와 Rack을 찾음
        # 부동소수점 오차 방지를 위해 0.5보다 큰지 확인
        assigned_c = [c for c in C if x[k, c].X > 0.5][0]
        assigned_r = [r for r in R if y[k, r].X > 0.5][0]
        
        # 완료 시간 확인
        end_time = E[k].X
        
        schedule_data.append({
            "주문 번호 (k)": k,
            "도착 시간 (t_k)": t[k],
            "작업 수량 (n_k)": n[k],
            "할당 랙 (r)": assigned_r,
            "할당 CP (c)": assigned_c,
            "완료 시간 (E_k)": round(end_time, 2)
        })
    
    # 3. Pandas DataFrame으로 변환 후 시간순 정렬
    df_schedule = pd.DataFrame(schedule_data)
    df_schedule = df_schedule.sort_values(by="도착 시간 (t_k)")
    
    # 4. 결과 출력
    print("=== 상세 분류 스케줄 타임라인 ===")
    print(df_schedule.head(60).to_string(index=False))
    df_schedule.to_csv("Model3_Schedule_Result.csv", index=False)

else:
    print("\n[실패] 제한 시간 내에 해를 찾지 못함.")