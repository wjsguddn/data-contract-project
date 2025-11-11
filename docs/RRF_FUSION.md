# RRF (Reciprocal Rank Fusion) 구현

## 개요

챗봇의 하이브리드 검색에 RRF(Reciprocal Rank Fusion) 융합 방식을 추가했습니다.

## 융합 방식 비교

### Weighted Fusion (기존 방식)
- **사용처**: Consistency Agent (A1 노드)
- **방법**: 점수 정규화 후 가중합
- **가중치**: Dense 0.85, Sparse 0.15
- **특징**: 
  - 점수 스케일에 민감
  - 가중치 튜닝 필요
  - Adaptive Weighting 적용 (Sparse 결과 없을 시 Dense 1.0)

### RRF (새로운 방식)
- **사용처**: Chatbot Agent
- **방법**: 순위 기반 융합
- **공식**: `score(d) = Σ 1/(k + rank_i(d))`
- **파라미터**: k=60 (일반적 최적값)
- **특징**:
  - 점수 스케일 독립적
  - 가중치 튜닝 불필요
  - 여러 시스템에서 공통으로 나타나는 문서 우대

## 구현 상세

### HybridSearcher 수정

```python
# 초기화 시 fusion_method 지정
searcher = HybridSearcher(
    azure_client=client,
    fusion_method="rrf"  # "weighted" (기본값) 또는 "rrf"
)
```

### 융합 메서드

#### 1. `fuse_scores()` - 라우터
```python
def fuse_scores(self, dense_results, sparse_results):
    if self.fusion_method == "rrf":
        return self._fuse_scores_rrf(dense_results, sparse_results)
    else:
        return self._fuse_scores_weighted(dense_results, sparse_results)
```

#### 2. `_fuse_scores_weighted()` - 기존 방식
- Min-Max 정규화
- 가중합 계산
- Adaptive Weighting 적용

#### 3. `_fuse_scores_rrf()` - RRF 방식
- 순위 맵 생성 (1-based)
- RRF 점수 계산: `1/(60 + rank)`
- 점수 순 정렬

## 사용 예시

### Chatbot (RRF 사용)
```python
# HybridSearchTool._load_user_contract_indexes()
searcher = HybridSearcher(
    azure_client=self.azure_client,
    fusion_method="rrf"  # RRF 사용
)
```

### A1 Node (Weighted 사용)
```python
# ArticleMatcher._get_or_create_searcher()
searcher = HybridSearcher(
    azure_client=self.azure_client,
    dense_weight=0.85
    # fusion_method 미지정 → 기본값 "weighted" 사용
)
```

## RRF 동작 예시

```python
# Dense 검색 결과
dense_results = [
    {"chunk_id": "제3조", "score": 0.92, "rank": 1},
    {"chunk_id": "제4조", "score": 0.78, "rank": 2},
    {"chunk_id": "제10조", "score": 0.65, "rank": 3}
]

# Sparse 검색 결과
sparse_results = [
    {"chunk_id": "제4조", "score": 12.5, "rank": 1},
    {"chunk_id": "제3조", "score": 11.8, "rank": 2},
    {"chunk_id": "제7조", "score": 9.3, "rank": 3}
]

# RRF 점수 계산 (k=60)
제3조: 1/(60+1) + 1/(60+2) = 0.0164 + 0.0161 = 0.0325
제4조: 1/(60+2) + 1/(60+1) = 0.0161 + 0.0164 = 0.0325
제10조: 1/(60+3) + 0 = 0.0159
제7조: 0 + 1/(60+3) = 0.0159

# 최종 순위: 제3조 ≈ 제4조 > 제10조 ≈ 제7조
```

## 성능 영향

### 계산 복잡도
- **Weighted**: O(k log k) - 정규화 + 병합 + 정렬
- **RRF**: O(k log k) - 순위 맵 + RRF 계산 + 정렬
- **차이**: 거의 없음 (~0.08ms)

### 응답 시간
- **전체 파이프라인**: 600-1900ms
- **융합 단계**: 0.1-0.2ms (전체의 0.01%)
- **영향**: 무시 가능

### 병목 구간
1. LLM 쿼리 생성: 500-1500ms
2. 임베딩 생성: 100-300ms
3. FAISS 검색: 10-50ms
4. Whoosh 검색: 5-20ms
5. **융합**: 0.1-0.2ms ← 무시 가능

## 장점

1. **점수 스케일 독립적**: Dense/Sparse 점수 범위 차이 무관
2. **정규화 불필요**: 계산 단순화
3. **검색 품질 향상**: 여러 연구에서 입증된 효과
4. **가중치 튜닝 불필요**: k=60으로 고정 가능
5. **하위 호환성**: A1 노드는 기존 방식 유지

## 참고 문헌

- Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009). "Reciprocal rank fusion outperforms condorcet and individual rank learning methods." SIGIR.
- 일반적으로 k=60이 최적값으로 알려져 있음
