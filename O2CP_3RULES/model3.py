import gurobipy as gp
from gurobipy import GRB
import random

# ==========================================
# 1. 인스턴스 데이터 세팅
# ==========================================
num_orders = 60
num_racks = 6
cps_per_rack = 10
num_cps = num_racks * cps_per_rack

# 집합 (Sets)
K = list(range(num_orders))
R = list(range(num_racks))
C = list(range(num_cps))
C_r = {r: list(range(r * cps_per_rack, (r + 1) * cps_per_rack)) for r in R}

# 파라미터 생성 (재현성을 위해 시드 고정)
random.seed(42)

t = {k: k * 5 for k in K}                           # 주문 투입 시간 (5초 간격)
d = {r: 10 + r * 5 for r in R}                      # 하역장 -> 랙 r까지의 AMR 이동 시간
p = {c: 5 + (c % cps_per_rack) * 2 for c in C}      # 랙 입구 -> CP c까지의 셔틀 사이클 타임
tau = {c: d[c // cps_per_rack] + p[c] for c in C}   # 해당 CP까지의 총 물리적 소요 시간 (비교용)

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
    (E[k] >= t[k] + gp.quicksum(d[r] * y[k, r] for r in R) + gp.quicksum(p[c] * x[k, c] for c in C) 
     for k in K), 
    name="timeline_amr"
)

# (5) 타임라인 제약 2: 단일 랙 셔틀 동기화 (Single Machine Scheduling)
m.addConstrs(
    (E[k] >= E[j] - M * (2 - y[k, r] - y[j, r]) + gp.quicksum(p[c] * x[k, c] for c in C)
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
# 5. 결과 확인
# ==========================================
if m.status == GRB.OPTIMAL or m.status == GRB.TIME_LIMIT:
    print(f"\n[최적화 완료] Makespan (Z): {Z.X:.2f} 초")
    
    # 랙별 워크로드 검증용 코드
    rack_counts = {r: sum(y[k, r].X for k in K) for r in R}
    print(f"랙별 주문 할당량: {rack_counts}")
else:
    print("\n[실패] 제한 시간 내에 해를 찾지 못함.")