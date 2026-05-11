# 3D Robotized Sorting System MILP Model

## 1. 연구 주제

본 프로젝트는 **3D Robotized Sorting System의 구조적 특성을 반영한 수리적 모델링 및 Gurobi 기반 최적화**를 목표로 한다.

기존 2D robotized sorting system은 일반적으로 다음과 같은 구조를 가진다.

```text
Loading Station → AMR/Robot → Collection Point
````

즉, AMR이 piece를 loading station에서 싣고 collection point(CP)에 직접 투입하는 구조이다.

반면 본 연구에서 다루는 3D sorter 시스템은 다음과 같은 구조를 가진다.

```text
Loading Station → Rack/Shuttle Handover Point → Collection Point
```

즉, AMR은 piece를 CP까지 직접 투입하지 않고, rack 앞 handover point까지 운반한다. 이후 rack에 배치된 shuttle이 해당 piece를 CP로 투입한다.

본 연구의 핵심은 다음과 같다.

> 같은 rack에 속한 여러 CP가 하나의 shuttle을 공유하므로, O2CP(Order-to-Collection Point) 문제와 rack-shuttle sequencing 문제가 결합된다.

---

## 2. 문제 정의

본 문제는 3D sorter 시스템에서 다음 의사결정을 동시에 고려한다.

1. **Piece-to-Order Assignment (P2O)**
   각 piece를 어떤 order에 배정할 것인가?

2. **Order-to-Collection Point Assignment (O2CP)**
   각 order를 어떤 CP에 배정할 것인가?

3. **Piece-to-Rack/Shuttle Assignment**
   piece가 배정된 CP가 속한 rack/shuttle module을 어떻게 결정할 것인가?

4. **Rack/Shuttle Sequencing**
   같은 rack/shuttle을 사용하는 piece들의 처리순서를 어떻게 정할 것인가?

5. **No-buffer AMR Waiting**
   rack 앞 buffer가 없으므로, shuttle이 사용 중이면 AMR은 piece를 들고 handover point에서 대기한다.

최종 목적은 모든 order가 완료되는 최종 시점, 즉 **makespan**을 최소화하는 것이다.

본 연구에서 makespan은 다음과 같이 정의한다.

> 모든 piece가 AMR 운반, rack handover, shuttle 투입 과정을 거쳐 각 order의 CP에 투입 완료되고, 모든 order가 완료되는 최종 시점

---

## 3. 시스템 가정

### Assumption 1

Rack 앞에는 item buffer가 없다.

### Assumption 2

AMR은 piece를 들고 rack handover point에 도착한 뒤, 해당 rack shuttle이 사용 가능해질 때까지 대기한다.

### Assumption 3

Handover가 완료되면 AMR은 즉시 다음 작업을 수행할 수 있다.

### Assumption 4

Rack당 shuttle은 1대이며, 한 번에 하나의 piece만 처리한다.

### Assumption 5

Shuttle은 handover point에서 piece를 받아 CP에 투입한 뒤, 다시 handover point로 복귀해야 다음 piece를 처리할 수 있다.

### Assumption 6

AMR 배정은 본 모델의 핵심 의사결정이 아니므로, 현재 코드에서는 round-robin 방식으로 사전 고정한다.

### Assumption 7

CP 재사용은 현재 버전에서 고려하지 않는다. 즉, 하나의 CP는 하나의 order만 담당한다.

---

## 4. 기존 2D Sorter 모델과의 차이점

기존 2D sorter에서는 order를 가까운 CP에 배정하면 AMR 이동거리가 줄어드는 효과가 있다. 따라서 O2CP 문제는 주로 CP 위치와 CP 점유 여부를 고려한다.

그러나 본 연구의 3D sorter에서는 CP가 rack 단위로 묶여 있고, 같은 rack의 CP들은 하나의 shuttle을 공유한다.

예를 들어 다음과 같은 구조를 생각한다.

```text
Rack 0
 ├─ CP0
 ├─ CP1
 ├─ CP2
 └─ CP3

Rack 0 담당 shuttle = 1대
```

이때 piece `p`가 CP0으로 가고, piece `p'`가 CP3으로 간다고 하자. CP0과 CP3은 서로 다른 CP이지만, 둘 다 Rack 0에 속해 있으므로 같은 shuttle을 사용해야 한다.

따라서 두 piece는 동시에 처리될 수 없고, 반드시 다음 둘 중 하나의 순서를 가져야 한다.

```text
p 먼저 처리 → p' 처리
```

또는

```text
p' 먼저 처리 → p 처리
```

이것이 본 모델에서 말하는 **rack-level capacity 제약**이다.

즉, CP-level로 보면 서로 다른 CP이지만, rack-level로 보면 동일한 shuttle이라는 하나의 자원을 공유한다.

---

## 5. 현재 코드 구성

본 프로젝트는 크게 두 개의 Python 파일과 하나의 CSV 데이터 파일로 구성된다.

```text
.
├── model_3d_sorter_compact.py
├── instance_sales_data.py
└── Online Sales Data.csv
```

### `model_3d_sorter_compact.py`

수리모델 본체가 들어 있는 파일이다.

포함 내용:

* Gurobi 모델 생성
* 변수 정의
* 목적식 정의
* 제약식 정의
* makespan 최소화
* compact formulation 적용

이 파일은 수리모델 구조를 담고 있으므로, 일반적으로 자주 수정하지 않는다.

### `instance_sales_data.py`

실행용 파일이다.

포함 내용:

* CSV 데이터 읽기
* piece 생성
* order demand 생성
* rack/CP 구조 생성
* AMR round-robin 배정
* 시간 파라미터 생성
* `model_3d_sorter_compact.py` 호출
* Gurobi 최적화 실행
* 결과 출력

실험 조건이나 파라미터를 바꾸고 싶을 때는 주로 이 파일을 수정한다.

### `Online Sales Data.csv`

실험용 주문 데이터이다.

현재 코드는 이 CSV에서 다음 정보를 사용한다.

| CSV 컬럼             | 사용 방식                      |
| ------------------ | -------------------------- |
| `Product Category` | SKU로 사용                    |
| `Units Sold`       | piece 수량 및 order demand 생성 |
| `Region`           | loading station 배정 기준      |
| `Product Name`     | 결과 추적용 참고 정보               |
| `Transaction ID`   | 결과 추적용 참고 정보               |
| `Date`             | 현재 모델에서는 직접 사용하지 않음        |
| `Unit Price`       | 현재 모델에서는 사용하지 않음           |
| `Total Revenue`    | 현재 모델에서는 사용하지 않음           |
| `Payment Method`   | 현재 모델에서는 사용하지 않음           |

---

## 6. CSV 데이터 전처리 정책

CSV 데이터는 Gurobi 모델에 바로 들어가지 않는다.
`instance_sales_data.py`에서 다음 정책에 따라 수리모델 입력 데이터로 변환된다.

### 6.1 SKU 생성

CSV의 `Product Category`를 SKU로 사용한다.

예:

```text
Electronics
Clothing
Books
Beauty Products
Sports
Home Appliances
```

현재 버전에서는 `Product Name`을 SKU로 쓰지 않는다.
이유는 `Product Name`을 SKU로 쓰면 상품명이 너무 세분화되어 P2O 문제가 약해질 수 있기 때문이다.

---

### 6.2 Piece 생성

CSV의 각 row에서 `Units Sold` 수량만큼 piece를 생성한다.

예를 들어 다음 row가 있다고 하자.

```text
Product Category = Electronics
Units Sold = 3
```

그러면 Electronics piece가 3개 생성된다.

```text
P0: Electronics
P1: Electronics
P2: Electronics
```

---

### 6.3 Order 생성

CSV row 여러 개를 하나의 order로 묶는다.

현재 기본 설정은 다음과 같다.

```python
ROWS_PER_ORDER = 3
```

즉, CSV row 3개를 하나의 order로 묶는다.

예:

```text
row 1~3   → Order 0
row 4~6   → Order 1
row 7~9   → Order 2
row 10~12 → Order 3
```

---

### 6.4 Order Demand 생성

하나의 order로 묶인 row들의 `Product Category`와 `Units Sold`를 합산하여 order demand를 만든다.

예를 들어 row 1~3이 다음과 같다고 하자.

| Row | Product Category | Units Sold |
| --: | ---------------- | ---------: |
|   1 | Electronics      |          2 |
|   2 | Home Appliances  |          1 |
|   3 | Clothing         |          3 |

그러면 Order 0의 demand는 다음과 같다.

| Order | Electronics | Home Appliances | Clothing |
| ----- | ----------: | --------------: | -------: |
| O0    |           2 |               1 |        3 |

동시에 piece는 다음과 같이 생성된다.

| Piece | 원본 Row | SKU             |
| ----: | -----: | --------------- |
|    P0 |  row 1 | Electronics     |
|    P1 |  row 1 | Electronics     |
|    P2 |  row 2 | Home Appliances |
|    P3 |  row 3 | Clothing        |
|    P4 |  row 3 | Clothing        |
|    P5 |  row 3 | Clothing        |

---

### 6.5 Piece Arrival Sequence

CSV row 순서를 piece 도착 순서로 사용한다.

같은 row에서 `Units Sold`가 여러 개이면 같은 SKU의 piece가 연속으로 생성된다.

현재 기본 설정은 다음과 같다.

```python
TIME_STEP_BETWEEN_PIECES = 2
```

따라서 piece 도착 가능 시간은 다음과 같이 생성된다.

| Piece | Arrival Time |
| ----: | -----------: |
|    P0 |            0 |
|    P1 |            2 |
|    P2 |            4 |
|    P3 |            6 |
|   ... |          ... |

---

### 6.6 Loading Station 배정

CSV의 `Region` 값을 loading station으로 매핑한다.

예:

```text
Asia    → L0
Europe  → L1
America → L2
```

실제 매핑은 코드에서 자동으로 생성된다.

---

### 6.7 AMR 배정

AMR 배정은 현재 최적화 대상이 아니다.

현재 코드는 piece 번호를 기준으로 round-robin 방식으로 AMR을 사전 배정한다.

예를 들어 AMR이 4대이면 다음과 같이 배정된다.

| Piece | Assigned AMR |
| ----: | -----------: |
|    P0 |         AMR0 |
|    P1 |         AMR1 |
|    P2 |         AMR2 |
|    P3 |         AMR3 |
|    P4 |         AMR0 |
|    P5 |         AMR1 |
|    P6 |         AMR2 |
|    P7 |         AMR3 |

즉, piece 번호를 AMR 수로 나눈 나머지를 이용한다.

```python
amr_of_piece = {p: p % NUM_AMR for p in P}
```

AMR이 4대이면 AMR별 처리 순서는 다음과 같다.

|  AMR | 처리 순서                     |
| ---: | ------------------------- |
| AMR0 | P0 → P4 → P8 → P12 → ...  |
| AMR1 | P1 → P5 → P9 → P13 → ...  |
| AMR2 | P2 → P6 → P10 → P14 → ... |
| AMR3 | P3 → P7 → P11 → P15 → ... |

---

## 7. 실행 방법

### 7.1 필요 환경

* Python
* Gurobi Optimizer
* Gurobi license
* `gurobipy`

Python용 Gurobi 패키지는 다음과 같이 설치할 수 있다.

```bash
pip install gurobipy
```

또는 conda 환경에서는 다음과 같이 설치할 수 있다.

```bash
conda install -c gurobi gurobi
```

---

### 7.2 실행 명령어

세 파일을 같은 폴더에 둔다.

```text
model_3d_sorter_compact.py
instance_sales_data.py
Online Sales Data.csv
```

이후 터미널에서 다음 명령어를 실행한다.

```bash
python instance_sales_data.py
```

---

## 8. 주요 설정값

`instance_sales_data.py`에서 주로 수정할 수 있는 값은 다음과 같다.

```python
NUM_CSV_ROWS = 12
ROWS_PER_ORDER = 3
NUM_LOADING_STATIONS = 3
NUM_AMR = 4
NUM_RACKS = 3
CP_PER_RACK = 4
TIME_STEP_BETWEEN_PIECES = 2
```

각 설정값의 의미는 다음과 같다.

| 설정값                        | 의미                      |
| -------------------------- | ----------------------- |
| `NUM_CSV_ROWS`             | CSV에서 몇 개 row를 사용할지     |
| `ROWS_PER_ORDER`           | 몇 개 row를 하나의 order로 묶을지 |
| `NUM_LOADING_STATIONS`     | loading station 수       |
| `NUM_AMR`                  | AMR 수                   |
| `NUM_RACKS`                | rack/shuttle module 수   |
| `CP_PER_RACK`              | rack당 CP 수              |
| `TIME_STEP_BETWEEN_PIECES` | piece 도착 간격             |

초기 테스트에서는 작은 규모로 시작하는 것을 권장한다.

예:

```python
NUM_CSV_ROWS = 12
ROWS_PER_ORDER = 3
```

이 경우 CSV 12개 row를 사용하고, 3개 row를 하나의 order로 묶으므로 총 4개 order가 생성된다.

---

## 9. 수리모형

### 9.1 Sets

| 기호      | 설명                                      |
| ------- | --------------------------------------- |
| `P`     | 현재 batch 또는 decision window 안의 piece 집합 |
| `O`     | active order 집합                         |
| `G`     | SKU 집합                                  |
| `C`     | collection point 집합                     |
| `B`     | rack/shuttle module 집합                  |
| `C_b`   | rack `b`에 속한 CP 집합                      |
| `K_AMR` | 같은 AMR이 연속으로 처리하는 piece 쌍 집합            |

---

### 9.2 Parameters

| 기호          | 설명                                                       |
| ----------- | -------------------------------------------------------- |
| `g_p`       | piece `p`의 SKU                                           |
| `l_p`       | piece `p`가 위치한 loading station                           |
| `d_og`      | order `o`가 SKU `g`를 필요로 하는 잔여 수량                         |
| `tau_LB_lb` | loading station `l`에서 rack `b` handover point까지 AMR 이동시간 |
| `tau_BL_bl` | AMR이 rack `b`에서 loading station `l`로 이동하는 시간             |
| `tau_BC_bc` | rack `b`의 shuttle이 CP `c`까지 piece를 투입하는 데 걸리는 시간         |
| `rho_bc`    | shuttle이 CP `c`에 투입한 뒤 handover point로 복귀하는 시간           |
| `h_b`       | rack `b`에서 AMR-shuttle handover에 걸리는 시간                  |
| `A_b`       | 현재 시점에서 rack/shuttle `b`가 사용 가능해지는 시간                    |
| `A_c`       | 현재 시점에서 CP `c`가 사용 가능해지는 시간                              |
| `S0_p`      | AMR이 piece `p` 운반을 시작할 수 있는 가장 이른 시간                     |
| `M`         | 충분히 큰 Big-M 상수                                           |

---

### 9.3 Decision Variables

| 변수        | 타입         | 설명                                               |
| --------- | ---------- | ------------------------------------------------ |
| `x_po`    | binary     | piece `p`를 order `o`에 배정하면 1                     |
| `y_oc`    | binary     | order `o`를 CP `c`에 배정하면 1                        |
| `m_pc`    | binary     | piece `p`가 CP `c`로 투입되면 1                        |
| `r_pb`    | binary     | piece `p`가 rack/shuttle `b`를 사용하면 1              |
| `q_pp'b`  | binary     | rack `b`에서 piece `p`가 `p'`보다 먼저 처리되면 1           |
| `S_p`     | continuous | AMR이 piece `p`를 싣고 출발하는 시간                       |
| `E_p`     | continuous | AMR이 piece `p`를 들고 rack handover point에 도착하는 시간  |
| `H_p`     | continuous | piece `p`의 AMR-shuttle handover 시작시간             |
| `G_p`     | continuous | AMR이 handover를 끝내고 다음 작업이 가능해지는 시간               |
| `D_p`     | continuous | piece `p`가 CP에 투입 완료되는 시간                        |
| `F_p`     | continuous | piece `p` 처리 후 shuttle이 다음 piece를 처리할 수 있게 되는 시간 |
| `W_p^AMR` | continuous | piece `p`를 운반한 AMR의 rack 앞 대기시간                  |
| `C_o`     | continuous | order `o`의 완료시간                                  |
| `C_max`   | continuous | 전체 시스템의 makespan                                 |

---

## 10. Objective Function

본 모델의 목적은 모든 order가 완료되는 최종 시점, 즉 makespan을 최소화하는 것이다.

```latex
minimize C_max
```

수식으로는 다음과 같다.

$$
\min C_{\max}
$$

---

## 11. Constraints

### 11.1 Piece-to-Order Assignment

각 piece는 정확히 하나의 order에 배정된다.

$$
\sum_{o \in O} x_{po} = 1
\qquad \forall p \in P
$$

해당 SKU를 필요로 하지 않는 order에는 piece를 배정할 수 없다.

$$
x_{po} = 0
\qquad \forall p \in P,\ o \in O \text{ such that } d_{o,g_p}=0
$$

order의 SKU 수요를 초과해서 piece를 배정할 수 없다.

$$
\sum_{p \in P: g_p=g} x_{po} \le d_{og}
\qquad \forall o \in O,\ g \in G
$$

---

### 11.2 Order-to-CP Assignment

각 order는 정확히 하나의 CP에 배정된다.

$$
\sum_{c \in C} y_{oc} = 1
\qquad \forall o \in O
$$

하나의 CP는 동시에 최대 하나의 order만 담당한다.

$$
\sum_{o \in O} y_{oc} \le 1
\qquad \forall c \in C
$$

---

### 11.3 Piece-Order-CP Linking

기존 formulation에서는 `w_poc` 보조변수를 사용했지만, 현재 compact formulation에서는 `w_poc`를 제거하고 `m_pc`를 `x_po`, `y_oc`와 직접 연결한다.

만약 piece `p`가 order `o`에 배정되고, order `o`가 CP `c`를 사용한다면, piece `p`는 CP `c`로 가야 한다.

$$
m_{pc} \ge x_{po} + y_{oc} - 1
\qquad \forall p \in P,\ o \in O,\ c \in C
$$

추가적으로, piece `p`가 order `o`에 배정된 경우, piece `p`는 order `o`가 사용하는 CP로만 갈 수 있다.

$$
m_{pc} \le y_{oc} + 1 - x_{po}
\qquad \forall p \in P,\ o \in O,\ c \in C
$$

각 piece는 정확히 하나의 CP로 투입된다.

$$
\sum_{c \in C} m_{pc} = 1
\qquad \forall p \in P
$$

---

### 11.4 Piece-to-Rack/Shuttle Linking

piece가 rack `b`에 속한 CP로 가면, 해당 piece는 rack/shuttle `b`를 사용한다.

$$
r_{pb} = \sum_{c \in C_b} m_{pc}
\qquad \forall p \in P,\ b \in B
$$

각 piece는 정확히 하나의 rack/shuttle을 사용한다.

$$
\sum_{b \in B} r_{pb} = 1
\qquad \forall p \in P
$$

---

### 11.5 AMR Start and Rack Arrival Time

AMR은 piece가 사용 가능해진 이후 출발할 수 있다.

$$
S_p \ge S^0_p
\qquad \forall p \in P
$$

AMR이 rack handover point에 도착하는 시간은 출발시간과 이동시간을 반영한다.

$$
E_p \ge S_p + \sum_{b \in B} \tau^{LB}*{l_p b} r*{pb}
\qquad \forall p \in P
$$

---

### 11.6 No-buffer Direct Handover

Rack 앞 buffer가 없으므로, AMR이 rack에 도착하기 전에는 handover가 시작될 수 없다.

$$
H_p \ge E_p
\qquad \forall p \in P
$$

rack/shuttle이 사용 가능해야 handover가 시작될 수 있다.

$$
H_p \ge \sum_{b \in B} A_b r_{pb}
\qquad \forall p \in P
$$

handover가 완료되어야 AMR은 다음 작업을 수행할 수 있다.

$$
G_p \ge H_p + \sum_{b \in B} h_b r_{pb}
\qquad \forall p \in P
$$

AMR의 rack 앞 대기시간은 rack 도착시간과 handover 시작시간의 차이로 계산된다.

$$
W^{AMR}_p = H_p - E_p
\qquad \forall p \in P
$$

---

### 11.7 Same AMR Consecutive Job Constraint

같은 AMR이 piece `p`를 처리한 뒤 piece `p'`를 처리한다면, `p'`의 출발은 `p`의 handover 완료 및 loading station 복귀 이후에 가능하다.

$$
S_{p'} \ge G_p + \sum_{b \in B} \tau^{BL}*{b l*{p'}} r_{pb}
\qquad \forall (p,p') \in K^{AMR}
$$

---

### 11.8 CP Availability

piece는 CP가 사용 가능해진 뒤에만 CP에 투입 완료될 수 있다.

$$
D_p \ge \sum_{c \in C} A_c m_{pc}
\qquad \forall p \in P
$$

---

### 11.9 Rack/Shuttle Processing Time

piece가 CP에 투입 완료되는 시간은 handover 시작시간, handover 시간, shuttle 이동시간을 반영한다.

$$
D_p \ge H_p + \sum_{c \in C}
\left( h_{b(c)} + \tau^{BC}*{b(c)c} \right)m*{pc}
\qquad \forall p \in P
$$

shuttle이 다음 piece를 처리할 수 있는 시간은 CP 투입 후 복귀시간까지 반영한다.

$$
F_p \ge H_p + \sum_{c \in C}
\left( h_{b(c)} + \tau^{BC}*{b(c)c} + \rho*{b(c)c} \right)m_{pc}
\qquad \forall p \in P
$$

---

### 11.10 Rack/Shuttle Single-processing Sequencing

같은 rack/shuttle을 사용하는 두 piece는 동시에 처리될 수 없다.

piece `p`가 piece `p'`보다 먼저 처리되는 경우:

$$
H_{p'} \ge F_p

* M(1-q_{pp'b})
* M(2-r_{pb}-r_{p'b})
  \qquad \forall p < p',\ b \in B
  $$

piece `p'`가 piece `p`보다 먼저 처리되는 경우:

$$
H_p \ge F_{p'}

* Mq_{pp'b}
* M(2-r_{pb}-r_{p'b})
  \qquad \forall p < p',\ b \in B
  $$

---

### 11.11 Order Completion Time

order `o`의 완료시간은 해당 order에 배정된 모든 piece의 CP 투입 완료시간 이후여야 한다.

$$
C_o \ge D_p - M(1-x_{po})
\qquad \forall p \in P,\ o \in O
$$

---

### 11.12 Makespan

전체 makespan은 모든 order 완료시간보다 크거나 같아야 한다.

$$
C_{\max} \ge C_o
\qquad \forall o \in O
$$

---

### 11.13 Variable Domains

이진변수:

$$
x_{po}, y_{oc}, m_{pc}, r_{pb}, q_{pp'b} \in {0,1}
$$

연속변수:

$$
S_p, E_p, H_p, G_p, D_p, F_p, W^{AMR}*p, C_o, C*{\max} \ge 0
$$

---

## 12. 계산 흐름

전체 계산 흐름은 다음과 같다.

```text
1. Online Sales Data.csv 읽기

2. CSV 전처리
   - Product Category를 SKU로 변환
   - Units Sold 수량만큼 piece 생성
   - ROWS_PER_ORDER개 row를 하나의 order로 묶음
   - order demand 생성
   - Region을 loading station으로 매핑

3. 시스템 파라미터 생성
   - rack 수
   - CP 수
   - rack별 CP 집합
   - AMR 이동시간
   - shuttle 이동시간
   - handover 시간
   - shuttle 복귀시간

4. AMR 배정
   - round-robin 방식으로 AMR을 piece에 사전 배정
   - K_AMR 생성

5. Gurobi 모델 생성
   - 변수 생성
   - 목적식 설정
   - 제약식 추가

6. 최적화 실행
   - C_max 최소화

7. 결과 출력
   - order별 CP 배정
   - piece별 order/CP/rack 배정
   - AMR 출발/도착/대기/handover 시간
   - shuttle 처리순서
   - order 완료시간
   - 최종 makespan
```

---

## 13. 결과 해석

최적화 결과에서 주로 확인할 항목은 다음과 같다.

| 결과                                 | 의미                                  |
| ---------------------------------- | ----------------------------------- |
| `Cmax`                             | 전체 order 완료시간 중 최댓값                 |
| `Order -> CP assignment`           | 각 order가 어느 CP에 배정되었는지              |
| `Piece assignment and timing`      | 각 piece의 order, CP, rack, AMR 시간 정보 |
| `AMR_wait`                         | AMR이 rack 앞에서 shuttle을 기다린 시간       |
| `Rack/Shuttle processing sequence` | 각 rack/shuttle에서 piece들이 처리된 순서     |
| `C_order`                          | order별 완료시간                         |

특히 본 연구에서는 `Rack/Shuttle processing sequence`와 `AMR_wait`가 중요하다.

이 값들은 같은 rack에 속한 CP들이 하나의 shuttle을 공유하기 때문에 발생하는 병목을 보여준다.

---

## 14. 현재 모델의 핵심 기여

본 모델의 핵심 기여는 다음과 같다.

1. 기존 2D sorter의 P2O-O2CP 구조를 3D sorter 구조로 확장하였다.

2. 같은 rack에 속한 CP들이 하나의 shuttle을 공유한다는 rack-level capacity를 모델에 반영하였다.

3. Rack 앞 buffer가 없다는 조건을 반영하여 AMR이 shuttle을 기다리는 no-buffer direct handover 구조를 모델링하였다.

4. O2CP 결정이 단순 CP 배정이 아니라 rack-shuttle 부하와 처리순서에 영향을 주는 문제로 확장됨을 수리모형으로 표현하였다.

---

## 15. 현재 모델의 한계

현재 모델은 초기 수리모델 검증을 위한 버전이므로 다음 한계가 있다.

1. **AMR 배정은 최적화하지 않음**
   현재는 round-robin 방식으로 AMR을 사전 배정한다.

2. **CP 재사용 없음**
   현재는 하나의 CP가 하나의 order만 담당한다.

3. **Shuttle은 매 작업 후 handover point로 복귀한다고 가정**
   실제 시스템에서 shuttle이 CP 간 직접 이동할 수 있다면 추가 모델링이 필요하다.

4. **Rack 앞 buffer 없음**
   본 연구의 핵심 가정이지만, 향후 buffer capacity가 있는 경우와 비교할 수 있다.

5. **AMR collision 및 경로 혼잡 미반영**
   AMR 간 충돌이나 통로 congestion은 현재 모델에 포함하지 않는다.

