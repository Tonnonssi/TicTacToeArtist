# -*- coding: utf-8 -*-
"""1월_27일_MCTS.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1w-zg4uafHAWhaPyXCGt6jh9lQYkWf4mV

# Import
"""

from google.colab import drive
drive.mount('/content/drive')

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from math import sqrt

"""# 00 Game Info"""

STATE_SIZE = (3,3)
N_ACTIONS = STATE_SIZE[0]*STATE_SIZE[1]
STATE_DIM = 3 # first player 정보 넣음
BOARD_SHAPE = (STATE_DIM, 3, 3)

"""# 01 HYPER PARAMS"""

C_PUCT = 2.5
N_SIMULATIONS = 100

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
device

"""# 02 Env+State"""

import os

# 파일 복사 명령어 실행
os.system('cp "/content/drive/My Drive/Colab Notebooks/공통 environment+state.ipynb" "/content/"')

import nbformat

notebook_path = "/content/공통 environment+state.ipynb"
with open(notebook_path, "r", encoding="utf-8") as f:
    notebook_content = nbformat.read(f, as_version=4)

# 각 코드 셀 출력 및 실행
for cell in notebook_content.cells:
    if cell.cell_type == "code":
        print(f"실행 중인 코드:\n{cell.source}\n{'='*40}")
        exec(cell.source)

"""# 03 MCTS"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import math

"""### 사전 준비 (PolicyValueNet 초기화 및 학습)"""

# 새로운 모델 설계
class PolicyValueNet(nn.Module):
    def __init__(self):
        super(PolicyValueNet, self).__init__()
        self.fc1 = nn.Linear(9, 64)
        self.fc2 = nn.Linear(64, 64)
        self.fc3 = nn.Linear(64, 9)  # 정책 예측
        self.value_head = nn.Linear(64, 1)  # 가치 예측

        for layer in [self.fc1, self.fc2, self.fc3, self.value_head]:
            nn.init.kaiming_normal_(layer.weight, nonlinearity="leaky_relu")
            if layer.bias is not None:
                nn.init.constant_(layer.bias, 0.01)

    def forward(self, x):
        x = F.leaky_relu(self.fc1(x), negative_slope=0.01)
        x = F.leaky_relu(self.fc2(x), negative_slope=0.01)
        policy_logits = self.fc3(x)
        value = torch.tanh(self.value_head(x))  # [-1, 1] 범위 보정
        return policy_logits, value


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
policy_model = PolicyValueNet().to(device)

# 가치 학습을 위한 간단한 학습 과정
optimizer = torch.optim.Adam(policy_model.parameters(), lr=0.005)
criterion = nn.MSELoss()

print("[DEBUG] Starting PolicyValueNet pre-training...")

for epoch in range(100):
    optimizer.zero_grad()

    board_tensor = torch.rand(1, 9).to(device)
    _, value = policy_model(board_tensor)

    target_value = torch.tensor([[0.5]], device=device)  # 학습 목표 값
    loss = criterion(value, target_value)
    loss.backward()
    optimizer.step()

    if epoch % 10 == 0:
        print(f"[DEBUG] Epoch {epoch}, Loss: {loss.item():.4f}")

print("[DEBUG] PolicyValueNet pre-training completed!")

"""###  Node_m 클래스 (MCTS 노드)
각 MCTS 노드가 게임 상태와 정책 확률, 방문 횟수, 가치 총합을 저장하도록 설계
"""

class Node_m: #MCTS에서 사용되는 노드 클래스
    def __init__(self, state, parent=None, prior_prob=1.0):
        self.state = state
        self.parent = parent
        self.prior_prob = prior_prob # 정책 신경망에서 예측된 행동 확률
        self.visit_count = 0 # 노드 방문 횟수
        self.total_value = 0.0 # 노드의 총 평가 가치
        self.children = {} # 행동(action) -> Node_m 매핑


    def expand(self, policy_probs): # 자식 노드 확장
        print(f"[DEBUG] expand() called with policy_probs type: {type(policy_probs)}")
        # policy_probs를 기반으로 valid_actions을 가져와서, 새로운 자식 노드를 생성
        # policy_probs가 ndarray인 경우 처리
        if isinstance(policy_probs, np.ndarray): # policy_probs가 ndarray인지 확인
            valid_actions = self.state.get_legal_actions()  # 유효한 행동 가져오기
            print(f"[DEBUG] Valid actions: {valid_actions}")
            print(f"[DEBUG] Policy probs: {policy_probs}")

            for action, prob in enumerate(policy_probs): # 인덱스와 확률로 순회
                # 유효하고 아직 확장되지 않은 경우
                if action in valid_actions and action not in self.children:
                    if prob > 0:  # 🔥 정책 확률이 0보다 큰 경우에만 확장
                        print(f"[DEBUG] Expanding action {action} with prob {prob:.4f}")
                        next_state = self.state.next(action) # 다음 상태 생성
                        # 자식 노드 추가
                        self.children[action] = Node_m(next_state, parent=self, prior_prob=prob)
                    else:
                        print(f"[WARNING] Skipping action {action} due to low policy prob: {prob:.6f}")

        else:
            for action, prob in policy_probs.items(): # 기존 로직 유지
                if action not in self.children: # 아직 확장되지 않은 경우
                    if prob > 0:
                        print(f"[DEBUG] Expanding action {action} with prob {prob:.4f}")
                        next_state = self.state.next(action) # 다음 상태 생성
                        # 자식 노드 추가
                        self.children[action] = Node_m(next_state, parent=self, prior_prob=prob)
                    else:
                        print(f"[WARNING] Skipping action {action} due to low policy prob: {prob:.6f}")


    def is_leaf(self): #자식 노드가 없는 경우 확인
        return len(self.children) == 0


    def get_ucb_score(self, total_visits): #UCB 점수를 계산하여 탐험과 활용의 균형을 맞춤
        if self.visit_count == 0:
            return float('inf')
        q_value = self.total_value / self.visit_count
        exploration_term = C_PUCT * self.prior_prob * (math.sqrt(total_visits) / (1 + self.visit_count))
        return q_value + exploration_term #q값과 탐색 가중치(C_PUCT)를 이용한 계산

"""### MCTS 실행"""

class MCTSAgent: #몬테카를로 트리 탐색 알고리즘 클래스
    def __init__(self, policy_model):
        self.policy_model = policy_model


    def run_simulation(self, root): #MCTS 시뮬레이션 실행
        node = root
        search_path = [node]

        # Selection
        while not node.is_leaf(): # 1. Selection: 트리를 따라 확장되지 않은 노드로 이동
            total_visits = sum(child.visit_count for child in node.children.values())
            # 자식 노드 중 UCB 점수가 최대인 노드 선택
            node = max(node.children.values(), key=lambda child: child.get_ucb_score(total_visits))
            search_path.append(node)

        # Expansion & Evaluation: 리프 노드 확장
        if not node.state.check_done()[0]:  #check_done: 게임 종료 여부 & 패배 여부 반환
            policy, value = self._evaluate_policy(node.state)
            print(f"[DEBUG] Evaluated value: {value:.2f}")  # 디버깅 추가
            node.expand(policy)
        else:
            value = self._evaluate_terminal(node.state)

        # Backpropagation: 부모 노드로 값을 전달
        self._backpropagate(search_path, value)


    def _evaluate_policy(self, state):
        board_tensor = torch.tensor(state.state - state.enemy_state, dtype=torch.float32).view(1, -1).to(device)

        with torch.no_grad(): #정책 및 상태 평가 (정책 신경망 활용)
            policy_logits, value = self.policy_model(board_tensor)

        policy_probs = torch.softmax(policy_logits, dim=-1).squeeze(0).cpu().numpy() #정책을 확률로 변환
        legal_actions = np.where(state.get_legal_actions() != 0)[0]
        action_probs = {action: policy_probs[action] for action in legal_actions}

        print(f"Policy probs from model: {policy_probs}")
        print(f"Action probs after filtering: {action_probs}")

        return action_probs, value.item()


    def _evaluate_terminal(self, state): #터미널 상태에서 가치 평가
        return state.get_reward(state)


    def _backpropagate(self, search_path, value): #시뮬레이션 결과를 역전파
        for node in reversed(search_path):
            node.visit_count += 1
            node.total_value += value  # 가치 업데이트가 확실히 반영됨
            print(f"[DEBUG] Backpropagation - Node visit_count: {node.visit_count}, total_value: {node.total_value:.2f}")

            value = -value  # 상대방 관점에서 반전


    def get_action_probs(self, root, temp=1.5): #행동 확률 계산 / 온도 적용하여 탐색과 활용 조정
        if not isinstance(root, Node_m):  # root가 Node인지 확인
            root = Node_m(root)  # 자동 변환 추가

        if not root.children:  # 자식 노드가 없을 경우
            num_actions = len(root.state.get_legal_actions())  # 가능한 행동 개수
            return np.ones(num_actions) / num_actions  # 균등 확률 반환

        visits = np.array([child.visit_count for child in root.children.values()])

        if visits.sum() == 0:  # 방문 횟수가 0인 경우 처리
            return np.ones_like(visits) / len(visits)

        if temp == 0:  # 가장 많이 방문한 행동 선택 (탐색 X)
            best_action = np.argmax(visits)
            probs = np.zeros_like(visits)
            probs[best_action] = 1
            return probs

        # 온도(temp) 조정: 낮을수록 가장 방문 많은 행동을 선택하는 경향
        visits = visits ** (1 / temp)
        return visits / visits.sum()


    def get_action(self, root, temp=1.0): #행동 확률에 따라 최종 행동 선택
        probs = self.get_action_probs(root, temp)
        if probs is None or len(probs) == 0:
            return np.random.choice(len(probs))  # 가능한 행동 중 랜덤 선택
        return np.random.choice(len(probs), p=probs)  # 행동 확률 기반 선택

"""## Test Code"""

state = State()
# 실행
mcts = MCTSAgent(policy_model)
root = Node_m(state)  # 초기 상태

for i in range(N_SIMULATIONS):
    print(f"\n[SIMULATION {i + 1}]")
    mcts.run_simulation(root)

    # 탐색 후 `get_action()`을 사용하여 행동 선택
    action = mcts.get_action(root, temp=1.0)
    print(f"[RESULT] Chosen action: {action}")

print("MCTS 실행 완료!")