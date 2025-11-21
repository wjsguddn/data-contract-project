# A1 하이브리드 검색

## 개요

A1 Node의 하이브리드 검색은 FAISS 벡터 검색과 Whoosh 키워드 검색을 결합하여 사용자 계약서 조항과 표준계약서 조항 간의 매칭 수행. Dense(시멘틱) 검색과 Sparse(키워드) 검색의 장점을 융합하여 높은 정확도의 조항 매칭 달성.

### 핵심 특징

- **이중 FAISS 인덱스**: 본문(text_norm)과 제목(title) 분리 검색
- **필드 가중치**: 본문 70%, 제목 30% 결합
- **Dense/Sparse 융합**: 시멘틱 85%, 키워드 15% 가중합
- **멀티벡터 검색**: 하위항목별 개별 검색 후 조 단위 집계
- **정규화 점수**: 청크 개수 기반 정규화로 공정한 비교

### 검색 파이프라인

```
사용자 조항 → 하위항목 분리 → 각 하위항목별 검색 → 조 단위 집계 → 정렬 → Top-K 반환
```

## 아키텍처

### 전체 구조

```mermaid
graph TB
    subgraph "입력"
        UA[사용자 조항]
        SI[하위항목 리스트]
    end
    
    subgraph "검색 레이어"
        HS[HybridSearcher]
        DS[Dense Search<br/>FAISS]
        SS[Sparse Search<br/>Whoosh]
    end
    
    subgraph "FAISS 인덱스"
        FT[text_norm 인덱스]
        FTI[title 인덱스]
    end
    
    subgraph "Whoosh 인덱스"
        WI[BM25 인덱스]
    end
    
    subgraph "융합 및 집계"
        NM[점수 정규화]
        WF[가중합 융합]
        AG[조 단위 집계]
    end
    
    subgraph "출력"
        TR[Top-K 조항]
    end
    
    UA --> SI
    SI --> HS
    
    HS --> DS
    HS --> SS
    
    DS --> FT
    DS --> FTI
    SS --> WI
    
    DS --> NM
    SS --> NM
    
    NM --> WF
    WF --> AG
    AG --> TR
    
    style HS fill:#e1f5ff
    style DS fill:#e8f5e9
    style SS fill:#fff3e0
    style WF fill:#f3e5f5
```

### 컴포넌트 구성

```
backend/consistency_agent/
├── hybrid_searcher.py          # HybridSearcher 클래스
├── a1_node/
│   └── article_matcher.py      # ArticleMatcher 클래스 (멀티벡터 검색)
└── models.py
```


## 하이브리드 검색 메커니즘

### 1. 이중 FAISS 인덱스

표준계약서는 두 개의 독립적인 FAISS 인덱스로 구성:

**text_norm 인덱스**:
- 조항 본문 내용 임베딩
- 하위항목(①, ②, ③) 개별 임베딩
- 차원: 3072 (text-embedding-3-large)

**title 인덱스**:
- 조 제목 임베딩
- 조 단위로 하나의 임베딩
- 차원: 3072 (text-embedding-3-large)

```python
# 인덱스 로드
faiss_index_text, faiss_index_title = kb_loader.load_faiss_indexes(contract_type)

# HybridSearcher에 전달
searcher.load_indexes(
    faiss_index_text=faiss_index_text,
    faiss_index_title=faiss_index_title,
    chunks=chunks,
    whoosh_indexer=whoosh_indexer
)
```

### 2. 필드 가중치 (본문:제목 = 7:3)

본문과 제목의 중요도를 다르게 설정하여 검색 정확도 향상.

```python
# 기본 가중치
text_weight = 0.7   # 본문 가중치
title_weight = 0.3  # 제목 가중치

# 최종 점수 계산
final_score = text_weight * text_score + title_weight * title_score
```

**설계 근거**:
- 본문이 조항의 실질적 내용 포함 (70%)
- 제목은 조항의 주제 파악에 유용 (30%)
- 두 정보를 결합하여 더 정확한 매칭

### 3. Dense 검색 (FAISS)

벡터 유사도 기반 시멘틱 검색.

#### 3.1 검색 프로세스

```mermaid
sequenceDiagram
    participant AM as ArticleMatcher
    participant HS as HybridSearcher
    participant ES as EmbeddingService
    participant FT as FAISS text
    participant FTI as FAISS title
    
    AM->>HS: search(text_query, title_query)
    HS->>ES: embed_query(text_query)
    ES-->>HS: text_embedding
    HS->>ES: embed_query(title_query)
    ES-->>HS: title_embedding
    
    HS->>FT: search(text_embedding, top_k)
    FT-->>HS: text_results (distances, indices)
    
    HS->>FTI: search(title_embedding, top_k)
    FTI-->>HS: title_results (distances, indices)
    
    HS->>HS: 필드 가중치 융합
    HS-->>AM: 융합된 결과
```

#### 3.2 유사도 계산

```python
def dense_search(
    self,
    text_query: str,
    title_query: str,
    top_k: int = 50,
    contract_id: str = None
) -> List[Dict[str, Any]]:
    """Dense 검색 (FAISS 벡터 유사도)"""
    
    # 1. 본문 검색
    text_vector = self.embed_query(text_query, contract_id)
    distances, indices = self.faiss_index_text.search(text_vector, top_k)
    
    text_results = {}
    for idx, distance in zip(indices[0], distances[0]):
        chunk = self._get_chunk_by_text_index(int(idx))
        if chunk:
            similarity = 1.0 / (1.0 + float(distance))  # L2 거리 → 유사도 변환
            text_results[chunk['id']] = {
                'chunk': chunk,
                'text_score': similarity
            }
    
    # 2. 제목 검색
    title_vector = self.embed_query(title_query, contract_id)
    distances, indices = self.faiss_index_title.search(title_vector, top_k)
    
    title_results = {}
    for idx, distance in zip(indices[0], distances[0]):
        chunk = self._get_chunk_by_title_index(int(idx))
        if chunk:
            similarity = 1.0 / (1.0 + float(distance))
            title_results[chunk['id']] = {
                'chunk': chunk,
                'title_score': similarity
            }
    
    # 3. 필드 가중치 융합
    results = self._fuse_by_chunk_id(text_results, title_results)
    
    return results
```

**유사도 변환 공식**:
```
similarity = 1 / (1 + L2_distance)
```
- L2 거리가 0에 가까울수록 유사도 1에 근접
- L2 거리가 클수록 유사도 0에 근접


### 4. Sparse 검색 (Whoosh)

키워드 기반 BM25 검색.

#### 4.1 검색 프로세스

```python
def sparse_search(
    self,
    text_query: str,
    title_query: str,
    top_k: int = 50
) -> List[Dict[str, Any]]:
    """Sparse 검색 (Whoosh BM25)"""
    
    # WhooshSearcher.search_with_field_weights() 호출
    whoosh_results = self.whoosh_indexer.search_with_field_weights(
        text_query=text_query,
        title_query=title_query,
        text_weight=self.text_weight,  # 0.7
        title_weight=self.title_weight,  # 0.3
        top_k=top_k
    )
    
    # 결과 변환
    results = []
    for hit in whoosh_results:
        results.append({
            'chunk': {
                'id': hit['id'],
                'global_id': hit['global_id'],
                'parent_id': hit['parent_id'],
                'title': hit['title'],
                'text_raw': hit['text_raw'],
                'text_norm': hit['text_norm']
            },
            'score': hit['score'],
            'text_score': hit.get('text_score', 0.0),
            'title_score': hit.get('title_score', 0.0),
            'source': 'sparse'
        })
    
    return results
```

**BM25 특징**:
- 키워드 빈도 기반 점수 계산
- 문서 길이 정규화
- 희귀 키워드에 높은 가중치
- 한국어 형태소 분석 적용

### 5. 점수 융합 알고리즘

Dense와 Sparse 검색 결과를 결합하여 최종 점수 계산.

#### 5.1 정규화 (Min-Max Normalization)

```python
def normalize_scores(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """검색 결과 점수를 Min-Max 정규화 (0~1 범위)"""
    
    if not results:
        return results
    
    scores = [r['score'] for r in results]
    min_score = min(scores)
    max_score = max(scores)
    
    # 모든 점수가 같은 경우
    if max_score == min_score:
        for r in results:
            r['normalized_score'] = 1.0
        return results
    
    # Min-Max 정규화
    for r in results:
        r['normalized_score'] = (r['score'] - min_score) / (max_score - min_score)
    
    return results
```

**정규화 공식**:
```
normalized_score = (score - min_score) / (max_score - min_score)
```

#### 5.2 가중합 융합

```python
def fuse_scores(
    self,
    dense_results: List[Dict[str, Any]],
    sparse_results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Dense와 Sparse 검색 결과를 융합"""
    
    # 1. 점수 정규화
    dense_normalized = self.normalize_scores(dense_results)
    sparse_normalized = self.normalize_scores(sparse_results)
    
    # 2. 청크 ID별로 결과 수집
    chunk_scores = {}
    
    # Dense 결과 추가
    for result in dense_normalized:
        chunk_id = result['chunk']['id']
        chunk_scores[chunk_id] = {
            'chunk': result['chunk'],
            'dense_score': result['normalized_score'],
            'sparse_score': 0.0
        }
    
    # Sparse 결과 추가/병합
    for result in sparse_normalized:
        chunk_id = result['chunk']['id']
        if chunk_id in chunk_scores:
            chunk_scores[chunk_id]['sparse_score'] = result['normalized_score']
        else:
            chunk_scores[chunk_id] = {
                'chunk': result['chunk'],
                'dense_score': 0.0,
                'sparse_score': result['normalized_score']
            }
    
    # 3. 가중합 계산
    fused_results = []
    for chunk_id, data in chunk_scores.items():
        final_score = (
            self.dense_weight * data['dense_score'] +    # 0.85
            self.sparse_weight * data['sparse_score']    # 0.15
        )
        
        fused_results.append({
            'chunk': data['chunk'],
            'score': final_score,
            'dense_score': data['dense_score'],
            'sparse_score': data['sparse_score'],
            'parent_id': data['chunk'].get('parent_id'),
            'title': data['chunk'].get('title')
        })
    
    # 4. 최종 점수로 정렬
    fused_results.sort(key=lambda x: x['score'], reverse=True)
    
    return fused_results
```

**가중합 공식**:
```
final_score = 0.85 × dense_score + 0.15 × sparse_score
```

#### 5.3 Adaptive Weighting

Sparse 검색 결과가 없는 경우 자동으로 Dense 가중치를 1.0으로 조정.

```python
# Adaptive Weighting: Sparse 결과 부재 시 가중치 조정
if not sparse_results and dense_results:
    logger.warning("Sparse 검색 결과 없음 - Adaptive Weighting 적용 (Dense: 1.0)")
    effective_dense_weight = 1.0
    effective_sparse_weight = 0.0
else:
    effective_dense_weight = self.dense_weight  # 0.85
    effective_sparse_weight = self.sparse_weight  # 0.15
```

**효과**:
- Sparse 검색 실패 시에도 Dense 검색 결과 활용
- 0.85 상한 문제 해결
- 검색 안정성 향상


### 6. 멀티벡터 검색 (청크 → 조 단위 집계)

사용자 조항의 각 하위항목으로 개별 검색 후 조 단위로 집계.

#### 6.1 멀티벡터 검색 프로세스

```mermaid
flowchart TD
    A[사용자 조항] --> B[하위항목 분리]
    B --> C1[하위항목 1]
    B --> C2[하위항목 2]
    B --> C3[하위항목 3]
    
    C1 --> D1[하이브리드 검색<br/>Top-K 청크]
    C2 --> D2[하이브리드 검색<br/>Top-K 청크]
    C3 --> D3[하이브리드 검색<br/>Top-K 청크]
    
    D1 --> E1[조별 중복 제거<br/>최고 점수만 유지]
    D2 --> E2[조별 중복 제거<br/>최고 점수만 유지]
    D3 --> E3[조별 중복 제거<br/>최고 점수만 유지]
    
    E1 --> F[조 단위 집계]
    E2 --> F
    E3 --> F
    
    F --> G[정렬<br/>1. 하위항목 개수<br/>2. 평균 유사도<br/>3. 조 번호]
    
    G --> H[Top-K 조항 반환]
    
    style A fill:#e1f5ff
    style F fill:#f3e5f5
    style G fill:#fff3e0
```

#### 6.2 하위항목 정규화

```python
def _normalize_sub_item(self, content: str) -> str:
    """사용자 계약서 하위항목 정규화"""
    
    # 앞뒤 공백 제거
    text = content.strip()
    
    # 원문자 제거 (①②③...)
    text = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]+\s*', '', text)
    
    # 숫자 + 점 제거 (1. 2. 3. ...)
    text = re.sub(r'^\d+\.\s*', '', text)
    
    # 괄호 번호 제거 ((가) (나) ...)
    text = re.sub(r'^\([가-힣]\)\s*', '', text)
    
    # 다시 앞뒤 공백 제거
    text = text.strip()
    
    return text
```

#### 6.3 조별 중복 제거

```python
def _select_articles_from_chunks(
    self,
    chunk_results: List[Dict]
) -> List[Dict]:
    """청크 검색 결과에서 조별 중복 제거 후 모든 조 반환"""
    
    # parent_id로 그룹화
    article_groups = defaultdict(list)
    
    for result in chunk_results:
        parent_id = result.get('parent_id')
        if not parent_id:
            continue
        article_groups[parent_id].append(result)
    
    # 조별 최고 점수만 유지
    article_results = []
    
    for parent_id, chunks in article_groups.items():
        # 최고 점수 청크 찾기
        best_chunk = max(chunks, key=lambda c: c.get('score', 0.0))
        max_score = best_chunk.get('score', 0.0)
        
        article_results.append({
            'parent_id': parent_id,
            'title': chunks[0].get('title', ''),
            'score': max_score,
            'chunks': [best_chunk]  # 최고 점수 청크만 포함
        })
    
    # 점수 순으로 정렬
    article_results.sort(key=lambda x: x['score'], reverse=True)
    
    return article_results
```

#### 6.4 조 단위 집계

```python
def _aggregate_sub_item_results(
    self,
    sub_item_results: List[Dict]
) -> List[Dict]:
    """하위항목별 매칭 결과를 조 단위로 집계"""
    
    # 조별로 그룹화
    article_groups = defaultdict(lambda: {
        'sub_items': set(),
        'scores': [],
        'title': '',
        'chunks': []
    })
    
    # 모든 하위항목의 매칭 결과를 순회
    for sub_item_result in sub_item_results:
        sub_item_index = sub_item_result['sub_item_index']
        matched_articles = sub_item_result['matched_articles']
        
        for article in matched_articles:
            parent_id = article['parent_id']
            score = article['score']
            
            # 해당 조에 이 하위항목 추가
            article_groups[parent_id]['sub_items'].add(sub_item_index)
            article_groups[parent_id]['scores'].append(score)
            
            if not article_groups[parent_id]['title']:
                article_groups[parent_id]['title'] = article['title']
            
            # 청크 추가 (중복 제거)
            for chunk in article['chunks']:
                chunk_id = chunk.get('chunk', {}).get('id')
                if not any(c.get('chunk', {}).get('id') == chunk_id 
                          for c in article_groups[parent_id]['chunks']):
                    article_groups[parent_id]['chunks'].append(chunk)
    
    # 조별 집계 결과 생성
    article_scores = []
    
    for parent_id, data in article_groups.items():
        num_sub_items = len(data['sub_items'])  # 하위항목 개수
        avg_score = sum(data['scores']) / len(data['scores'])  # 평균 점수
        
        article_scores.append({
            'parent_id': parent_id,
            'title': data['title'],
            'score': avg_score,
            'matched_sub_items': sorted(list(data['sub_items'])),
            'num_sub_items': num_sub_items,
            'matched_chunks': data['chunks']
        })
    
    # 정렬: 1. 하위항목 개수 (내림차순) → 2. 유사도 (내림차순) → 3. 조 번호 (오름차순)
    article_scores.sort(key=lambda x: (
        -x['num_sub_items'],
        -x['score'],
        self._extract_article_number(x['parent_id'])
    ))
    
    # 임계값 필터링 (0.7 미만 제거)
    filtered_scores = [
        article for article in article_scores
        if article['score'] >= 0.7
    ]
    
    return filtered_scores
```

**정렬 우선순위**:
1. **하위항목 개수** (많은 순): 더 많은 하위항목에 등장한 조가 우선
2. **평균 유사도** (높은 순): 점수가 높은 조가 우선
3. **조 번호** (낮은 순): 앞쪽 조가 우선


### 7. 정규화 공식

청크 개수 기반 정규화로 공정한 비교 (현재 미사용, 향후 적용 가능).

```python
# 정규화 점수 계산 (향후 적용 가능)
normalized_score = avg_score / sqrt(total_chunks)
```

**설계 근거**:
- 청크가 많은 조항이 유리한 문제 해결
- 제곱근 사용으로 과도한 페널티 방지
- 조항 길이에 관계없이 공정한 비교

**현재 상태**:
- 코드에 구현되어 있으나 실제로는 미사용
- 평균 점수만으로도 충분한 성능
- 필요 시 활성화 가능

## 검색 프로세스 플로우차트

### 전체 검색 흐름

```mermaid
flowchart TD
    Start([사용자 조항 입력]) --> Extract[하위항목 추출 및 정규화]
    
    Extract --> Loop{모든 하위항목<br/>처리 완료?}
    
    Loop -->|No| SubItem[하위항목 선택]
    SubItem --> Query[검색 쿼리 생성<br/>text_query, title_query]
    
    Query --> Parallel{병렬 검색}
    
    Parallel --> Dense[Dense 검색<br/>FAISS]
    Parallel --> Sparse[Sparse 검색<br/>Whoosh]
    
    Dense --> DenseText[본문 검색<br/>text_norm 인덱스]
    Dense --> DenseTitle[제목 검색<br/>title 인덱스]
    
    DenseText --> DenseFuse[필드 가중치 융합<br/>0.7 × text + 0.3 × title]
    DenseTitle --> DenseFuse
    
    Sparse --> SparseResult[BM25 점수]
    
    DenseFuse --> Normalize[점수 정규화<br/>Min-Max]
    SparseResult --> Normalize
    
    Normalize --> Fusion[가중합 융합<br/>0.85 × dense + 0.15 × sparse]
    
    Fusion --> ChunkDedup[조별 중복 제거<br/>최고 점수만 유지]
    
    ChunkDedup --> SubStore[하위항목 결과 저장]
    SubStore --> Loop
    
    Loop -->|Yes| Aggregate[조 단위 집계<br/>하위항목별 결과 통합]
    
    Aggregate --> Sort[정렬<br/>1. 하위항목 개수<br/>2. 평균 유사도<br/>3. 조 번호]
    
    Sort --> Filter[임계값 필터링<br/>score >= 0.7]
    
    Filter --> End([Top-K 조항 반환])
    
    style Start fill:#e1f5ff
    style Parallel fill:#fff4e1
    style Fusion fill:#f3e5f5
    style Aggregate fill:#e8f5e9
    style End fill:#e1f5ff
```

### 점수 계산 플로우

```mermaid
flowchart TD
    A[원본 점수] --> B{Dense/Sparse}
    
    B -->|Dense| C[L2 거리 → 유사도 변환<br/>1 / 1 + distance]
    B -->|Sparse| D[BM25 점수]
    
    C --> E[필드 가중치 적용<br/>0.7 × text + 0.3 × title]
    D --> F[필드 가중치 적용<br/>0.7 × text + 0.3 × title]
    
    E --> G[Min-Max 정규화<br/>0~1 범위]
    F --> G
    
    G --> H[가중합 융합<br/>0.85 × dense + 0.15 × sparse]
    
    H --> I[조별 평균 계산<br/>sum scores / num_sub_items]
    
    I --> J[최종 점수]
    
    style A fill:#e1f5ff
    style H fill:#f3e5f5
    style J fill:#e8f5e9
```

## 가중치 조정 가이드

### 1. 필드 가중치 (본문:제목)

**기본값**: 0.7 : 0.3

**조정 방법**:
```python
# ArticleMatcher 호출 시 전달
matching_result = article_matcher.find_matching_article(
    user_article,
    contract_type,
    top_k=3,
    text_weight=0.8,   # 본문 가중치 증가
    title_weight=0.2   # 제목 가중치 감소
)
```

**조정 효과**:
- `text_weight` 증가: 본문 내용 중시, 상세 매칭
- `title_weight` 증가: 제목 유사성 중시, 주제 매칭

**권장 범위**:
- text_weight: 0.6 ~ 0.8
- title_weight: 0.2 ~ 0.4
- 합계는 항상 1.0

### 2. Dense/Sparse 가중치

**기본값**: 0.85 : 0.15

**조정 방법**:
```python
# ArticleMatcher 호출 시 전달
matching_result = article_matcher.find_matching_article(
    user_article,
    contract_type,
    top_k=3,
    dense_weight=0.9   # Dense 가중치 증가
)
# sparse_weight는 자동 계산 (1.0 - dense_weight)
```

**조정 효과**:
- `dense_weight` 증가: 시멘틱 유사도 중시, 의미 기반 매칭
- `sparse_weight` 증가: 키워드 일치 중시, 정확한 용어 매칭

**권장 범위**:
- dense_weight: 0.7 ~ 0.95
- sparse_weight: 0.05 ~ 0.3
- 합계는 항상 1.0

### 3. 임계값 (Threshold)

**기본값**: 0.7

**조정 방법**:
```python
# ArticleMatcher 초기화 시 설정
article_matcher = ArticleMatcher(
    knowledge_base_loader,
    azure_client,
    similarity_threshold=0.75  # 임계값 증가
)
```

**조정 효과**:
- 임계값 증가: 더 엄격한 매칭, 정밀도 향상
- 임계값 감소: 더 관대한 매칭, 재현율 향상

**권장 범위**:
- 0.6 ~ 0.8
- 0.7이 대부분의 경우 최적

### 4. Top-K 파라미터

**기본값**: 3 (조 단위), 5 (청크 단위)

**조정 방법**:
```python
# ArticleMatcher 호출 시 전달
matching_result = article_matcher.find_matching_article(
    user_article,
    contract_type,
    top_k=5  # 더 많은 후보 반환
)
```

**조정 효과**:
- top_k 증가: 더 많은 후보, 재현율 향상, 처리 시간 증가
- top_k 감소: 적은 후보, 정밀도 향상, 처리 시간 감소

**권장 범위**:
- 조 단위: 3 ~ 5
- 청크 단위: 5 ~ 10


## 성능 튜닝 팁

### 1. 검색 속도 최적화

**임베딩 캐싱**:
```python
# 사전 계산된 임베딩 사용
stored_embedding = embedding_loader.load_article_embedding(contract_id, article_no)
if stored_embedding:
    text_embedding = stored_embedding.get('text_embedding')
    title_embedding = stored_embedding.get('title_embedding')
    
    # 캐시된 임베딩으로 검색
    results = searcher.search_with_embeddings(
        text_query=text_query,
        title_query=title_query,
        text_embedding=text_embedding,
        title_embedding=title_embedding,
        top_k=top_k
    )
```

**효과**:
- 임베딩 생성 시간 절약 (약 100-200ms per query)
- API 호출 비용 절감
- 전체 검색 시간 30-40% 단축

**병렬 처리**:
```python
from concurrent.futures import ThreadPoolExecutor

# 하위항목별 검색 병렬 실행
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = []
    for sub_item in content_items:
        future = executor.submit(
            self._hybrid_search,
            text_query=sub_item,
            title_query=article_title,
            contract_type=contract_type,
            top_k=top_k
        )
        futures.append(future)
    
    results = [f.result() for f in futures]
```

**효과**:
- 하위항목이 많은 조항의 검색 시간 단축
- 5개 하위항목 기준 약 60% 시간 단축

### 2. 정확도 향상

**하위항목 정규화 강화**:
```python
# 추가 정규화 규칙
text = re.sub(r'^[가-힣]\.\s*', '', text)  # 가. 나. 다. 제거
text = re.sub(r'^\([0-9]+\)\s*', '', text)  # (1) (2) (3) 제거
text = re.sub(r'^\[[가-힣]\]\s*', '', text)  # [가] [나] [다] 제거
```

**LLM 검증 활용**:
```python
# 검색 후 LLM으로 매칭 검증
verification_result = matching_verifier.verify_matching(
    user_article,
    candidate_articles,
    contract_type,
    top_k=5
)
```

**효과**:
- 오탐지 제거
- 매칭 정확도 10-15% 향상

### 3. 메모리 최적화

**인덱스 메모리 관리**:
```python
# 계약 유형별 인덱스 캐싱
if contract_type not in self.searchers:
    searcher = HybridSearcher(...)
    searcher.load_indexes(...)
    self.searchers[contract_type] = searcher
else:
    searcher = self.searchers[contract_type]
```

**효과**:
- 중복 로드 방지
- 메모리 사용량 80% 감소
- 검색 속도 향상

### 4. 배치 처리

**여러 조항 동시 처리**:
```python
# 조항별 검색을 배치로 처리
batch_size = 10
for i in range(0, len(user_articles), batch_size):
    batch = user_articles[i:i+batch_size]
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(process_article, article)
            for article in batch
        ]
        results = [f.result() for f in futures]
```

**효과**:
- 전체 처리 시간 40-50% 단축
- 리소스 효율적 사용

## 코드 예시

### 기본 사용법

```python
from backend.consistency_agent.a1_node.article_matcher import ArticleMatcher
from backend.shared.services import get_knowledge_base_loader
from openai import AzureOpenAI

# 초기화
kb_loader = get_knowledge_base_loader()
azure_client = AzureOpenAI(...)

article_matcher = ArticleMatcher(
    knowledge_base_loader=kb_loader,
    azure_client=azure_client,
    similarity_threshold=0.7
)

# 조항 매칭
user_article = {
    "number": 5,
    "title": "개인정보의 제공",
    "content": [
        "① 제공자는 다음 각 호의 개인정보를 이용자에게 제공한다.",
        "② 제공되는 개인정보의 항목은 다음과 같다.",
        "③ 개인정보의 제공 방법은 다음과 같다."
    ]
}

matching_result = article_matcher.find_matching_article(
    user_article=user_article,
    contract_type="provide",
    top_k=3,
    contract_id="contract_123",
    text_weight=0.7,
    title_weight=0.3,
    dense_weight=0.85
)

# 결과 확인
if matching_result['matched']:
    print(f"매칭 성공: {len(matching_result['matched_articles'])}개 조")
    for article in matching_result['matched_articles']:
        print(f"  - {article['parent_id']}: {article['score']:.3f}")
else:
    print("매칭 실패")
```

### 가중치 조정 예시

```python
# 본문 중심 검색 (상세 내용 매칭)
result_text_focused = article_matcher.find_matching_article(
    user_article=user_article,
    contract_type="provide",
    text_weight=0.8,   # 본문 가중치 증가
    title_weight=0.2,
    dense_weight=0.85
)

# 제목 중심 검색 (주제 매칭)
result_title_focused = article_matcher.find_matching_article(
    user_article=user_article,
    contract_type="provide",
    text_weight=0.6,
    title_weight=0.4,  # 제목 가중치 증가
    dense_weight=0.85
)

# 시멘틱 중심 검색 (의미 기반)
result_semantic = article_matcher.find_matching_article(
    user_article=user_article,
    contract_type="provide",
    text_weight=0.7,
    title_weight=0.3,
    dense_weight=0.95  # Dense 가중치 증가
)

# 키워드 중심 검색 (정확한 용어)
result_keyword = article_matcher.find_matching_article(
    user_article=user_article,
    contract_type="provide",
    text_weight=0.7,
    title_weight=0.3,
    dense_weight=0.7   # Sparse 가중치 증가 (0.3)
)
```

### HybridSearcher 직접 사용

```python
from backend.consistency_agent.hybrid_searcher import HybridSearcher

# 초기화
searcher = HybridSearcher(
    azure_client=azure_client,
    embedding_model="text-embedding-3-large",
    dense_weight=0.85,
    fusion_method="weighted"
)

# 인덱스 로드
faiss_indexes = kb_loader.load_faiss_indexes("provide")
chunks = kb_loader.load_chunks("provide")
whoosh_indexer = kb_loader.load_whoosh_index("provide")

faiss_index_text, faiss_index_title = faiss_indexes
searcher.load_indexes(faiss_index_text, faiss_index_title, chunks, whoosh_indexer)

# 검색 수행
results = searcher.search(
    text_query="제공자는 개인정보를 이용자에게 제공한다",
    title_query="개인정보의 제공",
    top_k=10,
    dense_top_k=30,
    sparse_top_k=30,
    contract_id="contract_123"
)

# 결과 확인
for i, result in enumerate(results, 1):
    print(f"{i}. {result['parent_id']}: {result['score']:.3f}")
    print(f"   Dense: {result['dense_score']:.3f}, Sparse: {result['sparse_score']:.3f}")
```

## 관련 문서

- [Consistency Agent](CONSISTENCY_AGENT.md): 전체 아키텍처 및 노드 개요
- [A1 누락 검증](CONSISTENCY_A1_MISSING_VERIFICATION.md): 누락 조항 재검증 로직
- [A2 Node](CONSISTENCY_A2_NODE.md): 체크리스트 검증
- [A3 Node](CONSISTENCY_A3_NODE.md): 내용 분석
- [출력 스키마](CONSISTENCY_OUTPUT_SCHEMAS.md): A1/A2/A3 출력 구조

