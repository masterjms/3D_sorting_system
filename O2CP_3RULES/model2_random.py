import gurobipy as gp
from gurobipy import GRB
import random
import numpy as np
import pandas as pd

# ==========================================
# 1. 인스턴스 데이터 세팅
# ==========================================
from data_loader import get_instance_data

csv_file_path = "data/E-Commerce DataSet.xlsx" 

# [개선] 물리 제원과 ERP 계층 구조가 반영된 파라미터 로드
K, R, C, C_r, t_orders, n_orders, d, p, tau = get_instance_data(csv_file_path, batch_size=90)

# ==========================================
# 2. 피스 레벨 데이터 매핑 구조 빌드
# ==========================================
P = []                 # 전체 피스 ID 리스트
P_k = {}               # 주문별 속한 피스들의 ID 리스트 {k: [i1, i2, ...]}
t_p = {}               # 피스별 고유 출발 타임스탬프 파라미터 (t_i)
piece_to_order = {}    # 피스 ID -> 주문 ID 역추적 딕셔너리

piece_idx = 0
for k in K:
    num_pieces = n_orders[k]
    base_t = t_orders[k] 
    P_k[k] = []
    
    # 동일 주문 내의 피스들이 5초 간격으로 연속 진입한다고 가정
    for p_num in range(num_pieces):
        P.append(piece_idx)
        P_k[k].append(piece_idx)
        t_p[piece_idx] = round(base_t + p_num * 5, 2)
        piece_to_order[piece_idx] = k
        piece_idx += 1

M = 2000 # 수치 안정성을 위한 현실적인 Big-M 값

# ==========================================
# 3. 몬테카를로 시뮬레이션 세팅
# ==========================================
num_replications = 30  # 무작위 실험 반복 횟수
makespans = []         # 각 실험의 Z값을 저장할 리스트
all_schedule_data = [] # 30번 전체의 상세 할당 결과를 담을 마스터 리스트

print(f"Model 2 (Random) Piece-level {num_replications}회 반복 실험 시작...\n")

for i in range(num_replications):
    # 매 반복마다 다른 시드 적용 및 무작위 할당표(Omega) 생성
    random.seed(2026 + i) 
    
    # K개의 주문에 할당할 겹치지 않는 CP를 무작위로 K개 추출
    shuffled_C = random.sample(C, len(K))
    
    Omega = {(k, c): 0 for k in K for c in C}
    for idx, k in enumerate(K):
        Omega[k, shuffled_C[idx]] = 1

    # ==========================================
    # 4. Gurobi 모형 선언 및 최적화
    # ==========================================
    env = gp.Env(empty=True)
    env.setParam("OutputFlag", 0) # 30번 도는 동안 화면 출력 끄기
    env.start()
    
    m = gp.Model(f"Model2_Random_iter_{i}", env=env)
    
    # [개선] 결정 변수: 할당은 주문(k) 기준, 시간(E)은 피스(i) 기준
    x = m.addVars(K, C, vtype=GRB.BINARY, name="x")
    y = m.addVars(K, R, vtype=GRB.BINARY, name="y")
    E = m.addVars(P, vtype=GRB.CONTINUOUS, name="E") # k가 아닌 i(피스)
    Z = m.addVar(vtype=GRB.CONTINUOUS, name="Z")
    
    m.setObjective(Z, GRB.MINIMIZE)
    
    # 기본 할당 제약
    m.addConstrs((gp.quicksum(x[k, c] for c in C) == 1 for k in K), name="assign_order")
    m.addConstrs((gp.quicksum(x[k, c] for k in K) <= 1 for c in C), name="unique_cp")
    m.addConstrs((y[k, r] == gp.quicksum(x[k, c] for c in C_r[r]) for k in K for r in R), name="map_rack")
    
    # 무작위 할당 강제
    m.addConstrs((x[k, c] == Omega[k, c] for k in K for c in C), name="force_random") 
    
    # 피스 레벨 물리 타임라인 제약 1: 기본 이송 (AMR + 셔틀 1회)
    m.addConstrs(
        (E[i] >= t_p[i] + gp.quicksum(d[r] * y[k, r] for r in R) + gp.quicksum(p[c] * x[k, c] for c in C)
         for k in K for i in P_k[k]),
        name="piece_base_timeline"
    )
    
    # 피스 레벨 물리 타임라인 제약 2: 셔틀 순차 대기열 (Queueing Interference)
    m.addConstrs(
        (E[i] >= E[j] - M * (2 - y[piece_to_order[i], r] - y[piece_to_order[j], r]) + gp.quicksum(p[c] * x[piece_to_order[i], c] for c in C)
         for i in P for j in P if j < i for r in R),
        name="shuttle_queue_interference"
    )
    
    m.addConstrs((Z >= E[i] for i in P), name="makespan")
    
    # 최적화 실행
    m.optimize()
    
    # ==========================================
    # 5. 현재 회차의 상세 결과 추출 및 마스터 리스트에 누적
    # ==========================================
    if m.status == GRB.OPTIMAL:
        makespans.append(Z.X)
        
        for k in K:
            assigned_c = [c for c in C if x[k, c].X > 0.5][0]
            assigned_r = [r for r in R if y[k, r].X > 0.5][0]
            
            # [개선] 주문 k의 완료 시간은 속한 피스들 중 가장 늦게 끝난 피스의 시간
            end_time = max(E[i].X for i in P_k[k])
            
            all_schedule_data.append({
                "반복 회차 (Iteration)": i + 1,
                "주문 번호 (k)": k,
                "도착 시간 (t_k)": t_orders[k],
                "작업 수량 (n_k)": n_orders[k],
                "할당 랙 (r)": assigned_r,
                "할당 CP (c)": assigned_c,
                "완료 시간 (E_k)": round(end_time, 2)
            })
            
        if (i + 1) % 5 == 0:
            print(f" {i + 1}회 완료... (최근 Makespan: {Z.X:.2f}초)")

# ==========================================
# 6. 최종 지표 출력 및 CSV 전체 저장
# ==========================================
makespans_array = np.array(makespans)

print("\n" + "="*50)
print(" [Model 2: Random Assignment (Piece-level)] 시뮬레이션 통계")
print("="*50)
print(f"▶ 최소 완료 시간 (Best Case)  : {np.min(makespans_array):.2f} 초")
print(f"▶ 최대 완료 시간 (Worst Case) : {np.max(makespans_array):.2f} 초")
print(f"▶ 평균 완료 시간 (Mean Z)     : {np.mean(makespans_array):.2f} 초")
print(f"▶ 표준 편차 (Std. Deviation) : {np.std(makespans_array):.2f} 초")
print("="*50)

df_all_schedules = pd.DataFrame(all_schedule_data)
df_all_schedules = df_all_schedules.sort_values(by=["반복 회차 (Iteration)", "도착 시간 (t_k)"])

output_filename = "Model2_random_Results.csv"
df_all_schedules.to_csv(output_filename, index=False)

print(f"데이터 저장 완료: {output_filename}")