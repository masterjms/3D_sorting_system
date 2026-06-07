import gurobipy as gp
from gurobipy import GRB
import random
import numpy as np
import pandas as pd  # CSV 저장을 위해 pandas 추가

# ==========================================
# 1. 인스턴스 데이터 세팅 (외부 전처리 모듈 연동)
# ==========================================
from data_loader import get_instance_data

csv_file_path = "data/Online Sales Data.csv"

# 전처리 데이터 로드
K, R, C, C_r, t, n, d, p, tau = get_instance_data(csv_file_path, batch_size=60)
M = 100000 

# ==========================================
# 2. 몬테카를로 시뮬레이션 세팅
# ==========================================
num_replications = 30  # 무작위 실험 반복 횟수
makespans = []         # 각 실험의 Z값을 저장할 리스트
all_schedule_data = [] # 30번 전체의 상세 할당 결과를 담을 마스터 리스트

print(f"Model 2 {num_replications}회 반복 실험\n")

for i in range(num_replications):
    # 매 반복마다 다른 시드 적용
    random.seed(2026 + i) 
    shuffled_C = random.sample(C, len(C))
    
    Omega = {(k, c): 0 for k in K for c in C}
    for k in K:
        Omega[k, shuffled_C[k]] = 1

    # ==========================================
    # 3. Gurobi 모형 선언 및 최적화
    # ==========================================
    env = gp.Env(empty=True)
    env.setParam("OutputFlag", 0)
    env.start()
    
    m = gp.Model(f"Model2_Random_iter_{i}", env=env)
    
    x = m.addVars(K, C, vtype=GRB.BINARY, name="x")
    y = m.addVars(K, R, vtype=GRB.BINARY, name="y")
    E = m.addVars(K, vtype=GRB.CONTINUOUS, name="E")
    Z = m.addVar(vtype=GRB.CONTINUOUS, name="Z")
    
    m.setObjective(Z, GRB.MINIMIZE)
    
    # 제약식
    m.addConstrs((gp.quicksum(x[k, c] for c in C) == 1 for k in K), name="assign_order")
    m.addConstrs((gp.quicksum(x[k, c] for k in K) <= 1 for c in C), name="unique_cp")
    m.addConstrs((y[k, r] == gp.quicksum(x[k, c] for c in C_r[r]) for k in K for r in R), name="map_rack")
    
    m.addConstrs((x[k, c] == Omega[k, c] for k in K for c in C), name="force_random") # 무작위 강제
    
    m.addConstrs((E[k] >= t[k] + gp.quicksum(d[r] * y[k, r] for r in R) + gp.quicksum((n[k] * p[c]) * x[k, c] for c in C) for k in K), name="timeline_amr")
    m.addConstrs((E[k] >= E[j] - M * (2 - y[k, r] - y[j, r]) + gp.quicksum((n[k] * p[c]) * x[k, c] for c in C) for k in K for j in range(k) for r in R), name="timeline_shuttle")
    m.addConstrs((Z >= E[k] for k in K), name="makespan")
    
    # 최적화 실행
    m.optimize()
    
    # ==========================================
    # 현재 회차의 상세 결과 추출 및 마스터 리스트에 누적
    # ==========================================
    if m.status == GRB.OPTIMAL:
        makespans.append(Z.X)
        
        for k in K:
            assigned_c = [c for c in C if x[k, c].X > 0.5][0]
            assigned_r = [r for r in R if y[k, r].X > 0.5][0]
            end_time = E[k].X
            
            all_schedule_data.append({
                "반복 회차 (Iteration)": i + 1,
                "주문 번호 (k)": k,
                "도착 시간 (t_k)": t[k],
                "작업 수량 (n_k)": n[k],
                "할당 랙 (r)": assigned_r,
                "할당 CP (c)": assigned_c,
                "완료 시간 (E_k)": round(end_time, 2)
            })
            
        if (i + 1) % 10 == 0:
            print(f" {i + 1}회 완료... (최근 Makespan: {Z.X:.2f}초)")

# ==========================================
# 4. 최종 지표 출력 및 CSV 전체 저장
# ==========================================
makespans_array = np.array(makespans)

print("\n" + "="*50)
print(" [Model 2: Random Assignment] 시뮬레이션 통계")
print("="*50)
print(f"▶ 최소 완료 시간 (Best Case)  : {np.min(makespans_array):.2f} 초")
print(f"▶ 최대 완료 시간 (Worst Case) : {np.max(makespans_array):.2f} 초")
print(f"▶ 평균 완료 시간 (Mean Z)     : {np.mean(makespans_array):.2f} 초")
print(f"▶ 표준 편차 (Std. Deviation) : {np.std(makespans_array):.2f} 초")
print("="*50)

# 마스터 리스트를 DataFrame으로 변환 후 CSV로 저장
df_all_schedules = pd.DataFrame(all_schedule_data)

# 보기 좋게 정렬 (회차 -> 도착 시간 순)
df_all_schedules = df_all_schedules.sort_values(by=["반복 회차 (Iteration)", "도착 시간 (t_k)"])

# CSV 파일 출력
output_filename = "Model2_random_Results.csv"
df_all_schedules.to_csv(output_filename, index=False)

print(f"데이터 저장 완료: {output_filename}")