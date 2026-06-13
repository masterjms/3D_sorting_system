import pandas as pd
import numpy as np

def get_instance_data(csv_path, batch_size=90, mean_arrival_interval=5.0):
    """
    새로운 E-Commerce DataSet의 구조(order_id 중복 행 존재, prod_qty 컬럼 사용)를 반영하여
    주문별 총 피스 수를 집계하고 계층형 스케줄링 파라미터를 생성하는 함수
    """
    # 1. ERP 데이터 로드
    df = pd.read_excel(csv_path, engine='openpyxl')
    
    # 2. [핵심] order_id 기준으로 그룹화하여 주문별 총 피스 수(prod_qty 합산) 계산
    # 주문 시계열 순서를 보존하기 위해 order_date의 첫 번째 값도 함께 가져옵니다.
    order_group = df.groupby('order_id').agg({
        'prod_qty': 'sum',
        'order_date': 'first'
    }).reset_index()
    
    # 주문 일자 순으로 정렬 후 배치 사이즈만큼 슬라이싱
    order_group = order_group.sort_values(by='order_date')
    batch_df = order_group.iloc[:batch_size].copy()

    batch_df = batch_df.reset_index(drop=True)
    
    # 3. 인덱스 및 수량(n_k) 매핑 (prod_qty 사용)
    K = list(range(batch_size))
    n = batch_df['prod_qty'].to_dict()  # {0: 1, 1: 2, 2: 1, ...}
    
    # 4. 주문 도착 시간(t_k) 시뮬레이션
    np.random.seed(42)
    inter_arrival = np.random.exponential(scale=mean_arrival_interval, size=batch_size)
    t_array = np.cumsum(inter_arrival).round(2)
    t_array = t_array - t_array[0]
    t = {k: t_array[k] for k in K}
    
    # 5. tSort3D 기반 설비 제원 및 셔틀 왕복 사이클 타임(p_c) 계산
    num_racks = 6
    cps_per_rack = 15
    R = list(range(num_racks))
    C = list(range(num_racks * cps_per_rack))
    C_r = {r: list(range(r * cps_per_rack, (r + 1) * cps_per_rack)) for r in R}
    
    rack_length = 2.5       
    rack_width = 0.635      
    rack_height = 2.2       
    speed_crane = 1.5       
    time_drop = 2.0         
    col_spacing = rack_length / 5  
    row_spacing = rack_height / 3  
    
    p = {} 
    for c in C:
        local_c = c % cps_per_rack
        col_idx = (local_c % 5) + 1  
        row_idx = (local_c // 5) + 1 
        dist_x = col_idx * col_spacing  
        dist_y = row_idx * row_spacing  
        pure_move_time = max(dist_x, dist_y) / speed_crane
        depth_move_time = (rack_width * 2) / (speed_crane * 0.5)  
        p[c] = round((pure_move_time * 2) + depth_move_time + time_drop, 2)
        
    # 6. AMR 이동 시간(d_r) 및 통합 타우(tau) 계산
    grid_size = 0.6  
    amr_speed = 2.0  
    io_spacing_grids = 2 
    
    d = {}
    tau = {}
    for r in R:
        row_idx = r % 3
        y_distance = (2 + row_idx * io_spacing_grids) * grid_size
        x_distance = 1.0 * grid_size  
        total_distance = x_distance + y_distance
        time_to_io = total_distance / amr_speed
        d[r] = round(time_to_io, 2)
        
    for r in R:
        for c in C_r[r]:
            tau[c] = round(d[r] + p[c], 2)
            
    return K, R, C, C_r, t, n, d, p, tau