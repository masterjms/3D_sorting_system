# O2CP_3RULES/data_loader.py

import pandas as pd
import numpy as np

def get_instance_data(csv_path, batch_size=60, mean_arrival_interval=5.0):
    """
    ERP 매출 데이터를 읽어와 Gurobi 모델이 필요한 파라미터로 변환하여 반환하는 함수
    """
    # 1. ERP 데이터 로드 및 배치 슬라이싱
    df = pd.read_csv(csv_path)
    batch_df = df.iloc[:batch_size].copy()
    
    # 2. 인덱스 및 수량(n_k) 추출
    K = list(range(batch_size))
    n = batch_df['Units Sold'].to_dict()
    
    # 3. 도착 시간(t_k) 시뮬레이션
    np.random.seed(42) # 동일한 결과를 위해 고정
    inter_arrival = np.random.exponential(scale=mean_arrival_interval, size=batch_size)
    t_array = np.cumsum(inter_arrival).round(2)
    t_array = t_array - t_array[0]
    t = {k: t_array[k] for k in K}
    
    # ---------------------------------------------------------
    # 4. tSort3D 기반 체비셰프 거리 측정
    # ---------------------------------------------------------
    num_racks = 6
    cps_per_rack = 10
    R = list(range(num_racks))
    C = list(range(num_racks * cps_per_rack))
    C_r = {r: list(range(r * cps_per_rack, (r + 1) * cps_per_rack)) for r in R}
    
    # tSort3D 물리적 스펙 정의
    speed_crane = 1.5  # m/s
    time_drop = 2.0    # 물건을 떨어뜨리는 데 걸리는 시간 (초)
    
    p = {} # CP별 셔틀 왕복 사이클 타임 (p_c)
    
    for c in C:
        # 현재 CP가 해당 랙 안에서 몇 번째 위치인지 (0 ~ 9)
        local_c = c % cps_per_rack 
        
        # 5x2 그리드로 좌표 맵핑
        col = (local_c % 5) + 1  # 1, 2, 3, 4, 5 열
        row = (local_c // 5) + 1 # 1, 2 층
        
        x_dist = col * 0.5  # 가로 거리 (최대 2.5m)
        y_dist = row * 1.1  # 세로 거리 (최대 2.2m)
        
        # X축과 Y축 각각의 이동 시간 계산
        time_x = x_dist / speed_crane
        time_y = y_dist / speed_crane
        
        # 체비셰프 거리에 따른 편도 이동 시간 (둘 중 오래 걸리는 시간)
        time_oneway = max(time_x, time_y)
        
        # 왕복 시간 + 드롭 시간 계산 (소수점 2자리 반올림)
        p[c] = round((time_oneway * 2) + time_drop, 2)
        
    # AMR의 랙간 이동 시간 (이 부분도 창고 도면이 있다면 디테일하게 변경 가능)
    d = {r: 10 + r * 5 for r in R} 
    tau = {c: d[c // cps_per_rack] + p[c] for c in C}
    
    return K, R, C, C_r, t, n, d, p, tau