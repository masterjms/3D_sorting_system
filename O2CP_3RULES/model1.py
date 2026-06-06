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

K = list(range(num_orders))
R = list(range(num_racks))
C = list(range(num_cps))
C_r = {r: list(range(r * cps_per_rack, (r + 1) * cps_per_rack)) for r in R}

random.seed(42)
t = {k: k * 5 for k in K}                           
d = {r: 10 + r * 5 for r in R}                      
p = {c: 5 + (c % cps_per_rack) * 2 for c in C}      
tau = {c: d[c // cps_per_rack] + p[c] for c in C}   

M = 100000 

# ==========================================
# 2. Gurobi 모형 선언
# ==========================================
m = gp.Model("Model1_Nearest_Assignment")

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

# (2) 글로벌 최단 시간 할당 제약 (Model 1의 핵심)
# 빈 CP 중 tau(총 소요 시간)가 가장 작은 곳을 선택하도록 강제
m.addConstrs(
    (tau[c] * x[k, c] <= tau[c_prime] + M * gp.quicksum(x[j, c_prime] for j in range(k))
     for k in K for c in C for c_prime in C if c != c_prime),
    name="global_nearest"
)

# (3) 타임라인 제약 1: AMR의 랙 라우팅 및 셔틀 CP 할당 시간
m.addConstrs(
    (E[k] >= t[k] + gp.quicksum(d[r] * y[k, r] for r in R) + gp.quicksum(p[c] * x[k, c] for c in C) 
     for k in K), 
    name="timeline_amr"
)

# (4) 타임라인 제약 2: 단일 랙 셔틀 동기화
m.addConstrs(
    (E[k] >= E[j] - M * (2 - y[k, r] - y[j, r]) + gp.quicksum(p[c] * x[k, c] for c in C)
     for k in K for j in range(k) for r in R), 
    name="timeline_shuttle"
)

# (5) Makespan 제약
m.addConstrs((Z >= E[k] for k in K), name="makespan")

# ==========================================
# 4. 최적화 실행 및 결과 출력
# ==========================================
m.setParam('TimeLimit', 600)
m.setParam('MIPGap', 0.01)
m.optimize()

if m.status == GRB.OPTIMAL or m.status == GRB.TIME_LIMIT:
    print(f"\n[최적화 완료] Makespan (Z): {Z.X:.2f} 초")
    rack_counts = {r: sum(y[k, r].X for k in K) for r in R}
    print(f"랙별 주문 할당량: {rack_counts}")
else:
    print("\n[실패] 해를 찾지 못함.")