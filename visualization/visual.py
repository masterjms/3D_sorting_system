import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# 1. 데이터 로드
df1 = pd.read_csv('Model1_Schedule_Result.csv')
df2 = pd.read_csv('Model2_random_Results.csv')
df3 = pd.read_csv('Model3_Schedule_Result.csv')

# ========================================================
# Model 2 대표 시나리오(Average Case) 자동 추출 로직
# ========================================================
m2_makespans = df2.groupby('반복 회차 (Iteration)')['완료 시간 (E_k)'].max()
mean_makespan = m2_makespans.mean()

# 30회 중 평균(mean)에 가장 가까운 완료 시간을 가진 회차 찾기
rep_iter = (m2_makespans - mean_makespan).abs().idxmin()
df2_rep = df2[df2['반복 회차 (Iteration)'] == rep_iter]
print(f"Model 2 대표 시나리오로 {rep_iter}회차 추출 (Makespan: {m2_makespans[rep_iter]:.2f}초)")

# ========================================================
# Plot 1: Makespan 비교 (Boxplot & Baseline)
# ========================================================
fig, ax = plt.subplots(figsize=(10, 6))

makespan_m1 = df1['완료 시간 (E_k)'].max()
makespan_m3 = df3['완료 시간 (E_k)'].max()

# Model 2는 30개의 데이터를 박스플롯으로 표현
sns.boxplot(y=m2_makespans, x=["Model 2 (Random 30 Runs)"]*len(m2_makespans), width=0.3, color='lightgray', ax=ax)

# Model 1과 3은 단일 확정해이므로 점(Scatter)과 점선(H-line)으로 관통
ax.scatter(["Model 1 (Nearest)", "Model 3 (Balancing)"], [makespan_m1, makespan_m3], color=['red', 'blue'], s=200, zorder=5)

ax.axhline(makespan_m1, color='red', linestyle='--', alpha=0.6, label=f'Model 1 ({makespan_m1:.1f}s)')
ax.axhline(makespan_m3, color='blue', linestyle='--', alpha=0.6, label=f'Model 3 ({makespan_m3:.1f}s)')

ax.set_ylabel('전체 완료 시간 / Makespan (초)', fontsize=12)
ax.set_title('모델별 전체 완료 시간(Makespan) 비교 및 변동성 분석', fontsize=15, fontweight='bold')
ax.legend()
plt.grid(axis='y', linestyle=':', alpha=0.7)
plt.savefig('makespan_comparison_all.png', dpi=300, bbox_inches='tight')
plt.close()

# ========================================================
# Plot 2: 간트 차트 (3개 모델 랙별 점유율 비교)
# ========================================================
fig, axes = plt.subplots(3, 1, figsize=(14, 15), sharex=True)

dfs = [df1, df2_rep, df3]
titles = [
    'Model 1 (거리 기반 우선 할당 - 앞쪽 랙 병목 현상)', 
    f'Model 2 (무작위 할당 - 평균적 분산 상태)', 
    'Model 3 (제안 모형 - 워크로드 밸런싱 최적화)'
]

for i, (df, title) in enumerate(zip(dfs, titles)):
    ax = axes[i]
    df_sorted = df.sort_values('도착 시간 (t_k)')
    
    for _, row in df_sorted.iterrows():
        rack = row['할당 랙 (r)']
        start = row['도착 시간 (t_k)']
        end = row['완료 시간 (E_k)']
        duration = end - start
        
        # 랙 번호별로 색상을 다르게 칠함
        color = plt.cm.tab10(rack / 6)
        ax.barh(rack, duration, left=start, height=0.6, color=color, edgecolor='black', alpha=0.8)
    
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_ylabel('Rack ID', fontsize=12)
    ax.set_yticks(range(6))
    ax.set_yticklabels([f'Rack {r}' for r in range(6)])
    ax.grid(axis='x', linestyle='--', alpha=0.5)

axes[2].set_xlabel('Time / 타임라인 (초)', fontsize=12)
plt.tight_layout()
plt.savefig('gantt_chart_comparison_all.png', dpi=300, bbox_inches='tight')
plt.close()

# ========================================================
# Plot 3: 누적 처리량 차트 (Cumulative Throughput)
# ========================================================
plt.figure(figsize=(10, 6))

df1_sorted = df1.sort_values('완료 시간 (E_k)')
df2_rep_sorted = df2_rep.sort_values('완료 시간 (E_k)')
df3_sorted = df3.sort_values('완료 시간 (E_k)')

# 스텝(Step) 차트를 사용하여 계단식으로 주문 완료를 표현
plt.step(df1_sorted['완료 시간 (E_k)'], np.arange(1, len(df1_sorted)+1), label='Model 1 (Nearest)', color='red', linewidth=2)
plt.step(df2_rep_sorted['완료 시간 (E_k)'], np.arange(1, len(df2_rep_sorted)+1), label=f'Model 2 (Random Avg)', color='gray', linewidth=2, linestyle='-.')
plt.step(df3_sorted['완료 시간 (E_k)'], np.arange(1, len(df3_sorted)+1), label='Model 3 (Balancing)', color='blue', linewidth=2)

plt.title('시간 경과에 따른 시스템 누적 주문 처리량(Throughput)', fontsize=15, fontweight='bold')
plt.xlabel('Time / 경과 시간 (초)', fontsize=12)
plt.ylabel('완료된 누적 주문 수 (Count)', fontsize=12)
plt.legend(loc='lower right')
plt.grid(True, linestyle=':', alpha=0.7)
plt.savefig('cumulative_throughput_all.png', dpi=300, bbox_inches='tight')
plt.close()

print("시각화 차트 3종 생성 완료!")