import gurobipy as gp
from gurobipy import GRB
from data_loader import get_instance_data

def run_agv_simulation(model_type, sets, params):
    """
    model_type: 'Model_A' (Nearest-Time) or 'Model_B' (Filled-count Balancing)
    """
    env = gp.Env(empty=True)
    env.setParam('OutputFlag', 1)
    env.start()
    m = gp.Model(f"AGV_{model_type}", env=env)
    
    K, I, R, C = sets['K'], sets['I'], sets['R'], sets['C']
    M, lam = params['M'], params['lam']
    
    # --- 변수 선언 ---
    x = m.addVars(K, C, vtype=GRB.BINARY, name="x")
    y = m.addVars(K, R, vtype=GRB.BINARY, name="y")
    
    A = m.addVars(I, vtype=GRB.CONTINUOUS, name="A")
    H = m.addVars(I, vtype=GRB.CONTINUOUS, name="H")
    W = m.addVars(I, vtype=GRB.CONTINUOUS, name="W")
    E = m.addVars(I, vtype=GRB.CONTINUOUS, name="E")
    U = m.addVars(I, vtype=GRB.CONTINUOUS, name="U")
    C_k = m.addVars(K, vtype=GRB.CONTINUOUS, name="C_k")
    
    # --- 공통 할당 제약 ---
    m.addConstrs((gp.quicksum(x[k, c] for c in C) == 1 for k in K), name="assign_order")
    m.addConstrs((gp.quicksum(x[k, c] for k in K) <= 1 for c in C), name="assign_cp")
    m.addConstrs((y[k, r] == gp.quicksum(x[k, c] for c in sets['C_r'][r]) 
                  for k in K for r in R), name="link_cp_rack")

    # --- 핵심 제약 (분기) ---
    if model_type == 'Model_A':
        for k_idx, k in enumerate(K):
            for c in C:
                for c_prime in C:
                    sum_prev_x = gp.quicksum(x[k_p, c_prime] for k_p in K[:k_idx])
                    m.addConstr(params['tau'][c] * x[k, c] <= params['tau'][c_prime] + M * sum_prev_x)

    elif model_type == 'Model_B':
        for k_idx, k in enumerate(K):
            for r in R:
                for r_prime in R:
                    sum_prev_y_r = gp.quicksum(y[k_p, r] for k_p in K[:k_idx])
                    sum_prev_y_rp = gp.quicksum(y[k_p, r_prime] for k_p in K[:k_idx])
                    m.addConstr(sum_prev_y_r <= sum_prev_y_rp + M * (1 - y[k, r]))
        
        for k_idx, k in enumerate(K):
            for r in R:
                for c in sets['C_r'][r]:
                    for c_prime in sets['C_r'][r]:
                        sum_prev_x = gp.quicksum(x[k_p, c_prime] for k_p in K[:k_idx])
                        m.addConstr(params['tau'][c] * x[k, c] <= params['tau'][c_prime] + M * sum_prev_x)

    # --- Piece-level 시간 제약 ---
    for i in I:
        k_i = sets['k_of_i'][i]
        m.addConstr(A[i] == params['a'][i] + gp.quicksum(params['d'][r] * y[k_i, r] for r in R))
        m.addConstr(H[i] >= A[i])
        m.addConstr(W[i] == H[i] - A[i])
        m.addConstr(E[i] == H[i] + params['h'] + gp.quicksum(params['q'][c] * x[k_i, c] for c in C))
        m.addConstr(U[i] == H[i] + params['h'] + gp.quicksum(params['p'][c] * x[k_i, c] for c in C))
        
        i_idx = I.index(i)
        for j_idx in range(i_idx):
            j = I[j_idx]
            k_j = sets['k_of_i'][j]
            for r in R:
                m.addConstr(H[i] >= U[j] - M * (2 - y[k_i, r] - y[k_j, r]))

    m.addConstrs((C_k[k] >= E[i] for k in K for i in sets['I_k'][k]), name="OrderEnd")

    # --- 최적화 ---
    obj = gp.quicksum(C_k[k] for k in K) + lam * gp.quicksum(W[i] for i in I)
    m.setObjective(obj, GRB.MINIMIZE)
    m.setParam('TimeLimit', 600) 
    m.optimize()
    
    if m.SolCount > 0:
        print(f"[{model_type}] 최적해 발견! Obj Val: {m.objVal}")
        return m
    else:
        print(f"[{model_type}] 최적해를 찾지 못했습니다. Status: {m.status}")
        return None

if __name__ == "__main__":
    # 데이터 경로 지정
    CSV_PATH = "data/E-Commerce_DataSet.xlsx"
    
    # 1. 데이터 로드 및 전처리
    print("데이터를 전처리 중입니다...")
    sets, params = get_instance_data(CSV_PATH, batch_size=30)  # 테스트용 30개
    print(f"총 Order 수: {len(sets['K'])}, 총 Piece 수: {len(sets['I'])}")
    
    # 2. Model A 실행
    print("\n--- Model A (최근접 시간 할당) 실행 ---")
    model_A_result = run_agv_simulation('Model_A', sets, params)
    
    # 3. Model B 실행
    print("\n--- Model B (Filled-count Balancing 할당) 실행 ---")
    model_B_result = run_agv_simulation('Model_B', sets, params)