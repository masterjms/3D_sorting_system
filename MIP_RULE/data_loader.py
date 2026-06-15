import pandas as pd
import numpy as np

def get_instance_data(csv_path, batch_size=90):
    # 1. ERP 데이터 로드 및 Piece Sequence 보존
    df = pd.read_excel(csv_path, engine='openpyxl')

    # 수량이 0 이하인 row는 제거
    df = df[df['prod_qty'] > 0].copy()

    # 실제 투입 순서를 보존하기 위한 정렬
    # transaction_id, line_id 같은 세부 순서 컬럼이 있으면 같이 쓰는 것이 좋음
    sort_cols = []
    if 'order_date' in df.columns:
        sort_cols.append('order_date')
    if 'transaction_id' in df.columns:
        sort_cols.append('transaction_id')
    if 'line_id' in df.columns:
        sort_cols.append('line_id')

    if sort_cols:
        df = df.sort_values(by=sort_cols, kind='mergesort').reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    # 2. 단일 wave에 포함할 order 선택
    # order는 첫 등장 순서 기준으로 batch_size개 선택
    selected_order_ids = df['order_id'].drop_duplicates().iloc[:batch_size].tolist()

    # 선택된 order에 해당하는 row만 유지
    batch_df = df[df['order_id'].isin(selected_order_ids)].copy().reset_index(drop=True)

    # 원본 order_id를 내부 index k로 변환
    order_to_k = {order_id: k for k, order_id in enumerate(selected_order_ids)}
    k_to_order_id = {k: order_id for order_id, k in order_to_k.items()}

    K = list(range(len(selected_order_ids)))

    I = []
    I_k = {k: [] for k in K}
    k_of_i = {}

    # 디버깅용: piece가 원래 어떤 order_id, 어떤 row에서 왔는지 저장
    piece_info = {}

    piece_idx = 0

    # 3. 원본 row 순서를 따라 piece 생성
    for row_idx, row in batch_df.iterrows():
        original_order_id = row['order_id']
        k = order_to_k[original_order_id]
        qty = int(row['prod_qty'])

        for _ in range(qty):
            I.append(piece_idx)
            I_k[k].append(piece_idx)
            k_of_i[piece_idx] = k

            piece_info[piece_idx] = {
                'original_order_id': original_order_id,
                'internal_order_k': k,
                'source_row': row_idx,
                'order_date': row['order_date'] if 'order_date' in batch_df.columns else None
            }

            piece_idx += 1

    # 확정적 피스 방출 시간: piece sequence 기준 5초 간격
    a = {i: 5.0 * idx for idx, i in enumerate(I)}
    
    # 4. 랙 내부 설비 제원 세팅 (5열 3층 구조)
    num_racks = 6
    cps_per_rack = 15 # 5 x 3
    R = list(range(num_racks))
    C = list(range(num_racks * cps_per_rack))
    C_r = {r: list(range(r * cps_per_rack, (r + 1) * cps_per_rack)) for r in R}

    if len(K) > len(C):
        raise ValueError(
        f"Infeasible instance: number of orders ({len(K)}) exceeds number of CPs ({len(C)})."
    )
    
    # 랙 물리적 제원 및 속도
    rack_length = 2.5       
    rack_width = 0.635      
    rack_height = 2.2       
    speed_crane = 1.5       
    time_drop = 2.0         
    
    col_spacing = rack_length / 5  # 5열 간격
    row_spacing = rack_height / 3  # 3층 간격
    h_val = 2.0                    # Handover time
    
    p = {} # 셔틀 왕복 시간
    q = {} # 셔틀 편도 시간 (I/O -> CP)
    
    for c in C:
        local_c = c % cps_per_rack
        col_idx = (local_c % 5) + 1  # 1~5열
        row_idx = (local_c // 5) + 1 # 1~3층
        
        dist_x = col_idx * col_spacing  
        dist_y = row_idx * row_spacing  
        
        # 체비셰프 로직: 수평(열)과 수직(층) 중 더 오래 걸리는 축의 시간이 실제 순수 이동 시간
        pure_move_time = max(dist_x, dist_y) / speed_crane
        depth_move_time = (rack_width * 2) / (speed_crane * 0.5)  
        
        q[c] = round(pure_move_time + depth_move_time/2 + time_drop, 2)
        p[c] = round((pure_move_time * 2) + depth_move_time + time_drop, 2)
        
    # 5. AMR 주행/대기 차선 분리 (양열 마주보기 레이아웃 완벽 반영)
    grid_size = 0.6  
    amr_speed = 2.0  
    
    # 가정: 로딩 스테이션 -> 주행 차선 -> 대기 차선 진입 시 X축으로 3그리드 소요
    x_dist_to_parking = 3 * grid_size  
    
    # 가정: 첫 랙까지의 Y축 오프셋 및 랙 간의 Y축 간격(피치)
    y_offset = 2 * grid_size           
    rack_pitch = (rack_length / grid_size) + 1 # 랙 길이 + I/O 여유 공간
    
    d = {}
    tau = {}
    for r in R:
        row_idx = r % 3  
        
        # 쌍 단위로 같은 Y축 이동 거리를 가짐
        y_distance = y_offset + (row_idx * rack_pitch * grid_size)
        
        # 맨해튼 거리 (X축 진입 + Y축 주행)
        total_manhattan_dist = x_dist_to_parking + y_distance
        
        d[r] = round(total_manhattan_dist / amr_speed, 2)
        
    print(f"양방향 레이아웃 랙 거리(d): {d}")
    
    # 타우(추정 소요 시간) 계산: 도착시간 + 핸드오버 + 셔틀편도시간
    for r in R:
        for c in C_r[r]:
            tau[c] = round(d[r] + h_val + q[c], 2)
            
    sets = {
    'K': K,
    'I': I,
    'R': R,
    'C': C,
    'C_r': C_r,
    'I_k': I_k,
    'k_of_i': k_of_i,
    'order_to_k': order_to_k,
    'k_to_order_id': k_to_order_id,
    'piece_info': piece_info
}
    params = {'a': a, 'd': d, 'q': q, 'p': p, 'h': h_val, 'tau': tau, 'M': 10000, 'lam': 0.5}
    
    return sets, params