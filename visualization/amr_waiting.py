import pandas as pd
import matplotlib.pyplot as plt

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# 1. 데이터 로드
df1 = pd.read_csv('Model1_Schedule_Result.csv')
df3 = pd.read_csv('Model3_Schedule_Result.csv')

# 2. 동일한 주문번호 k 선정 (둘 다 n_k=6인 주문번호 8번을 예시로 사용)
k = 8 
p_c = 4.0 

def get_wait_data(df, order_k):
    order = df[df['주문 번호 (k)'] == order_k].iloc[0]
    t_arrival = order['도착 시간 (t_k)'] + (10 + order['할당 랙 (r)'] * 5)
    n_k = order['작업 수량 (n_k)']
    
    data = []
    shuttle_ready_time = t_arrival
    
    for i in range(int(n_k)):
        start_time = max(shuttle_ready_time, t_arrival)
        wait_time = start_time - t_arrival
        end_time = start_time + p_c
        shuttle_ready_time = end_time
        data.append({'Piece': i+1, 'Wait': wait_time, 'Processing': p_c, 'Start': start_time})
    return pd.DataFrame(data), t_arrival

# 데이터 추출
df_m1, arrival1 = get_wait_data(df1, k)
df_m3, arrival3 = get_wait_data(df3, k)

# 3. 시각화 (좌우 비교)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), sharey=True)

# Model 1
ax1.barh(df_m1['Piece'], df_m1['Wait'], left=arrival1, color='orange', height=0.6)
ax1.barh(df_m1['Piece'], df_m1['Processing'], left=df_m1['Start'], color='skyblue', height=0.6)
ax1.set_title(f'Model 1: Nearest CP (Wait: {df_m1["Wait"].sum()}s)', fontweight='bold')
ax1.set_xlabel('Time (s)')
ax1.set_ylabel('Piece ID')
ax1.grid(axis='x', linestyle='--', alpha=0.5)

# Model 3
ax2.barh(df_m3['Piece'], df_m3['Wait'], left=arrival3, color='orange', height=0.6)
ax2.barh(df_m3['Piece'], df_m3['Processing'], left=df_m3['Start'], color='skyblue', height=0.6)
ax2.set_title(f'Model 3: Proposed Balancing (Wait: {df_m3["Wait"].sum()}s)', fontweight='bold')
ax2.set_xlabel('Time (s)')
ax2.grid(axis='x', linestyle='--', alpha=0.5)

plt.suptitle(f'Order {k} (n_k=6): AMR 대기 시간 비교', fontsize=16)
plt.tight_layout(rect=[0, 0.03, 1, 0.95])
plt.savefig('model_comparison_waiting_time.png', dpi=300, bbox_inches='tight')
plt.show()