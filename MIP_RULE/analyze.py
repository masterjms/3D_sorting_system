import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd
import os

# 논문용 폰트 및 스타일 세팅
plt.rcParams['font.family'] = 'Malgun Gothic' # 윈도우 맑은고딕 (맥은 'AppleGothic')
plt.rcParams['axes.unicode_minus'] = False
plt.style.use('seaborn-v0_8-whitegrid')

# 결과 이미지를 저장할 디렉토리 생성
SAVE_DIR = "results"
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

def extract_kpis(model, sets, model_name):
    """Gurobi 모델 객체에서 핵심 KPI 추출"""
    K, I = sets['K'], sets['I']
    
    # 1. Makespan (가장 늦게 끝난 주문의 완료 시간)
    c_k_vals = [model.getVarByName(f"C_k[{k}]").X for k in K]
    makespan = max(c_k_vals)
    
    # 2. 총 대기 시간 및 평균 대기 시간
    w_vals = [model.getVarByName(f"W[{i}]").X for i in I]
    total_wait = sum(w_vals)
    avg_wait = total_wait / len(I) if I else 0
    
    print(f"========== [ {model_name} KPI ] ==========")
    print(f"1. Makespan (C_max): {makespan:.2f} 초")
    print(f"2. 총 AMR 대기 시간: {total_wait:.2f} 초")
    print(f"3. 피스당 평균 대기 시간: {avg_wait:.2f} 초")
    print(f"=========================================\n")
    
    return {'makespan': makespan, 'total_wait': total_wait, 'avg_wait': avg_wait}

def plot_gantt_chart(model_A, model_B, sets):
    """랙 셔틀의 순차 처리 과정을 보여주는 간트 차트"""
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    I, R = sets['I'], sets['R']
    
    for idx, (m, name, ax) in enumerate(zip([model_A, model_B], ['Model A (Nearest-Time)', 'Model B (Filled-count Balancing)'], axes)):
        yticks = []
        yticklabels = []
        
        for r in R:
            yticks.append(r)
            yticklabels.append(f"Rack {r}")
            # 랙 r에 할당된 피스들 찾기
            for i in I:
                k_i = sets['k_of_i'][i]
                y_val = m.getVarByName(f"y[{k_i},{r}]").X
                if y_val > 0.5:
                    start = m.getVarByName(f"H[{i}]").X
                    end = m.getVarByName(f"U[{i}]").X
                    duration = end - start
                    
                    # 간트 바 그리기
                    ax.barh(r, duration, left=start, height=0.6, color='skyblue', edgecolor='black')
        
        ax.set_title(f"Shuttle Operations Gantt Chart - {name}", fontsize=14, fontweight='bold')
        ax.set_yticks(yticks)
        ax.set_yticklabels(yticklabels)
        ax.set_ylabel("Racks")
    
    axes[1].set_xlabel("Time (seconds)", fontsize=12)
    plt.tight_layout()
    
    # 300 dpi로 고해상도 저장
    save_path = os.path.join(SAVE_DIR, "gantt_chart.png")
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"[저장 완료] 간트 차트: {save_path}")
    plt.show()

def plot_cp_heatmap(model_A, model_B, sets):
    """랙 및 CP별 작업 부하(Workload) 분산 히트맵"""
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    K, C, R = sets['K'], sets['C'], sets['R']
    
    for idx, (m, name, ax) in enumerate(zip([model_A, model_B], ['Model A', 'Model B'], axes)):
        # 6 Racks x 15 CPs 매트릭스 초기화
        heatmap_data = np.zeros((len(R), 15)) 
        
        for k in K:
            for c in C:
                if m.getVarByName(f"x[{k},{c}]").X > 0.5:
                    r = c // 15
                    local_c = c % 15
                    # 해당 CP에 할당된 피스 수만큼 카운트 추가
                    piece_count = len(sets['I_k'][k])
                    heatmap_data[r, local_c] += piece_count
                    
        sns.heatmap(heatmap_data, annot=True, cmap="YlOrRd", ax=ax, cbar=True, linewidths=.5)
        ax.set_title(f"CP Workload Heatmap - {name}", fontsize=14)
        ax.set_ylabel("Rack Index")
        ax.set_xlabel("Local CP Index (0~14)")
        
    plt.tight_layout()
    
    # 300 dpi로 고해상도 저장
    save_path = os.path.join(SAVE_DIR, "cp_heatmap.png")
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"[저장 완료] CP 히트맵: {save_path}")
    plt.show()

def plot_cumulative_wait_time(model_A, model_B, sets):
    """시간 흐름에 따른 누적 AMR 대기 시간 비교"""
    plt.figure(figsize=(10, 6))
    I = sets['I']
    
    for m, name, color in zip([model_A, model_B], ['Model A', 'Model B'], ['red', 'blue']):
        # 피스별 방출 시간과 대기 시간 매핑
        time_wait_pairs = []
        for i in I:
            arrival_time = m.getVarByName(f"A[{i}]").X
            wait_time = m.getVarByName(f"W[{i}]").X
            time_wait_pairs.append((arrival_time, wait_time))
            
        # 도착 시간 기준으로 정렬
        time_wait_pairs.sort(key=lambda x: x[0])
        times = [x[0] for x in time_wait_pairs]
        waits = [x[1] for x in time_wait_pairs]
        cumulative_waits = np.cumsum(waits)
        
        plt.plot(times, cumulative_waits, label=name, color=color, linewidth=2)

    plt.title("Cumulative AMR Waiting Time over Time", fontsize=15, fontweight='bold')
    plt.xlabel("AMR Arrival Time at Rack (seconds)", fontsize=12)
    plt.ylabel("Cumulative Waiting Time (seconds)", fontsize=12)
    plt.legend(fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    # 300 dpi로 고해상도 저장
    save_path = os.path.join(SAVE_DIR, "cumulative_wait_time.png")
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"[저장 완료] 누적 대기시간 그래프: {save_path}")
    plt.show()

def export_piece_details_to_excel(model_A, model_B, sets, save_dir="results"):
    """각 피스(Piece)별 할당 결과와 상세 시간 로그를 엑셀 파일로 추출"""
    excel_path = os.path.join(save_dir, "Piece_Scheduling_Details.xlsx")
    
    # 엑셀 엔진 실행 (openpyxl 필요)
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        for m, name in zip([model_A, model_B], ['Model_A', 'Model_B']):
            data = []
            
            for i in sets['I']:
                k = sets['k_of_i'][i]
                
                # 1. 해당 피스(주문)가 할당된 Rack과 CP 찾기
                assigned_c = None
                assigned_r = None
                for c in sets['C']:
                    if m.getVarByName(f"x[{k},{c}]").X > 0.5:
                        assigned_c = c
                        for r in sets['R']:
                            if m.getVarByName(f"y[{k},{r}]").X > 0.5:
                                assigned_r = r
                                break
                        break
                
                # 2. 시간 변수들 추출
                a_time = m.getVarByName(f"A[{i}]").X
                h_time = m.getVarByName(f"H[{i}]").X
                w_time = m.getVarByName(f"W[{i}]").X
                e_time = m.getVarByName(f"E[{i}]").X
                u_time = m.getVarByName(f"U[{i}]").X
                
                # 3. 데이터 행(Row) 구성
                data.append({
                    'Piece_ID': i,
                    'Order_ID': k,
                    'Assigned_Rack': assigned_r,
                    'Assigned_CP': assigned_c,
                    'AMR_Arrival_A': round(a_time, 2),
                    'Handover_Start_H': round(h_time, 2),
                    'AMR_Wait_Time_W': round(w_time, 2),
                    'Piece_End_E': round(e_time, 2),
                    'Shuttle_Release_U': round(u_time, 2)
                })
            
            # DataFrame 변환 후 엑셀 시트에 기록
            df = pd.DataFrame(data)
            df.to_excel(writer, sheet_name=name, index=False)
            
    print(f"[저장 완료] 엑셀 상세 결과 리포트: {excel_path}")