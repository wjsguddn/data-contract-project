# Design 문서

## 개요

A2 노드(체크리스트 검증)는 A1 노드의 매칭 결과를 기반으로 활용안내서의 체크리스트 항목을 LLM을 사용하여 검증합니다. 사용자 계약서의 각 조항이 매칭된 표준 조항의 체크리스트 요구사항을 충족하는지 자동으로 평가하고, 결과를 구조화된 형태로 저장합니다.

## 아키텍처

### 전체 플로우

```
1. A2 노드 실행
   ↓
2. A1 매칭 결과 로드 (ValidationResult.completeness_check)
   ↓
3. 체크리스트 데이터 로드 (JSON 파일)
   ↓
4. Global ID 기반 체크리스트 필터링
   ↓
5. 사용자 조항별 체크리스트 검증 (LLM)
   ↓
6. 검증 결과 집계 및 통계 계산
   ↓
7. DB 저장
   └─ ValidationResult.checklist_validation
```

### 컴포넌트 구조

```
ChecklistCheckNode (a2_node.py)
├─ check_checklist()
│  ├─ _load_a1_results() → A1 매칭 결과 로드
│  ├─ _filter_checklists() → global_id 기반 필터링
│  ├─ _verify_article() → 조항별 검증
│  ├─ _calculate_statistics() → 통계 계산
│  ├─ _save_to_db() → DB 저장
│  └─ _export_to_json() → JSON 파일 생성
│
├─ ChecklistLoader
│  ├─ load_checklist() → JSON 파일 로드
│  └─ filter_by_global_ids() → global_id 필터링
│
└─ ChecklistVerifier
   ├─ verify_batch() → 배치 검증 (LLM)
   ├─ verify_single() → 단일 항목 검증 (LLM)
   ├─ verify_with_context() → 표준 조항 컨텍스트 포함 검증
   └─ handle_low_confidence() → 신뢰도 기반 재검증
```

## 컴포넌트 설계

### ChecklistLoader

**역할**: 체크리스트 데이터 로드 및 필터링

```python
class ChecklistLoader:
    """활용안내서 체크리스트 로더"""
    
    def __init__(self):
        self._cache = {}  # 계약 유형별 캐시
    
    def load_checklist(self, contract_type: str) -> List[Dict]:
        """
        체크리스트 JSON 파일 로드
        
        Args:
            contract_type: 계약 유형
                - "provide": 데이터 제공형
                - "create": 데이터 창출형
                - "process": 데이터 가공서비스형
                - "brokerage_provider": 데이터 중개거래형 (제공자-운영자)
                - "brokerage_user": 데이터 중개거래형 (이용자-운영자)
            
        Returns:
            체크리스트 항목 리스트
            [
                {
                    "check_text": str,
                    "reference": str,
                    "global_id": str
                }
            ]
            
        Raises:
            FileNotFoundError: 체크리스트 파일이 없는 경우
            ValueError: 지원하지 않는 contract_type인 경우
        """
        # 지원하는 계약 유형 검증
        valid_types = ['provide', 'create', 'process', 'brokerage_provider', 'brokerage_user']
        if contract_type not in valid_types:
            raise ValueError(f"지원하지 않는 계약 유형: {contract_type}. 유효한 유형: {valid_types}")
        
        # 캐시 확인
        if contract_type in self._cache:
            logger.info(f"체크리스트 캐시 히트: {contract_type}")
            return self._cache[contract_type]
        
        # 파일 경로 생성
        file_path = f"data/chunked_documents/guidebook_chunked_documents/checklist_documents/{contract_type}_gud_contract_check_chunks_flat.json"
        
        # 파일 존재 확인
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"체크리스트 파일을 찾을 수 없습니다: {file_path}")
        
        # 파일 로드
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                checklist_data = json.load(f)
            
            logger.info(f"체크리스트 로드 완료: {contract_type} ({len(checklist_data)} 항목)")
            
            # 캐시 저장
            self._cache[contract_type] = checklist_data
            return checklist_data
            
        except json.JSONDecodeError as e:
            raise ValueError(f"체크리스트 JSON 파싱 실패: {file_path}, 오류: {e}")
        except Exception as e:
            raise RuntimeError(f"체크리스트 로드 중 오류 발생: {e}")
    
    def filter_by_global_ids(
        self,
        checklist_data: List[Dict],
        global_ids: List[str]
    ) -> List[Dict]:
        """
        global_id로 체크리스트 필터링
        
        Args:
            checklist_data: 전체 체크리스트
            global_ids: 필터링할 global_id 리스트
            
        Returns:
            필터링된 체크리스트 (중복 제거)
        """
        filtered = []
        seen_texts = set()
        
        for item in checklist_data:
            if item['global_id'] in global_ids:
                # 중복 제거 (check_text 기준)
                if item['check_text'] not in seen_texts:
                    filtered.append(item)
                    seen_texts.add(item['check_text'])
        
        return filtered
```

### ChecklistVerifier

**역할**: LLM을 사용한 체크리스트 검증

```python
class ChecklistVerifier:
    """LLM 기반 체크리스트 검증기"""
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
    
    def verify_batch(
        self,
        user_clause_text: str,
        checklist_items: List[Dict],
        batch_size: int = 10
    ) -> List[Dict]:
        """
        여러 체크리스트 항목을 배치로 검증
        
        Args:
            user_clause_text: 사용자 조항 전문
            checklist_items: 체크리스트 항목 리스트
            batch_size: 배치 크기 (기본 10개)
            
        Returns:
            검증 결과 리스트
            [
                {
                    "check_text": str,
                    "reference": str,
                    "std_global_id": str,
                    "result": "YES" | "NO",
                    "evidence": str | None,
                    "confidence": float
                }
            ]
        """
        results = []
        
        # 배치 단위로 처리
        for i in range(0, len(checklist_items), batch_size):
            batch = checklist_items[i:i+batch_size]
            
            try:
                batch_results = self._verify_batch_llm(user_clause_text, batch)
                results.extend(batch_results)
            except Exception as e:
                logger.error(f"배치 검증 실패: {e}, 개별 검증으로 폴백")
                # 배치 실패 시 개별 검증
                for item in batch:
                    try:
                        result = self.verify_single(user_clause_text, item)
                        results.append(result)
                    except Exception as e2:
                        logger.error(f"개별 검증 실패: {e2}, 항목 건너뜀")
                        continue
        
        return results
    
    def _verify_batch_llm(
        self,
        user_clause_text: str,
        checklist_items: List[Dict]
    ) -> List[Dict]:
        """
        LLM을 사용한 배치 검증
        
        프롬프트 구조:
        - 사용자 조항 전문
        - 체크리스트 항목 1~N
        - 각 항목에 대해 YES/NO + 근거 + 신뢰도 요청
        """
        # 체크리스트 항목을 번호와 함께 포맷팅
        checklist_text = ""
        for idx, item in enumerate(checklist_items, 1):
            checklist_text += f"{idx}. {item['check_text']}\n"
        
        prompt = f"""
다음 계약서 조항이 아래 체크리스트 요구사항들을 충족하는지 검증해주세요.

[계약서 조항]
{user_clause_text}

[체크리스트]
{checklist_text}

각 항목에 대해 다음 형식으로 답변해주세요:
1. 결과: YES 또는 NO
2. 근거: 판단 근거가 되는 계약서 내용 (YES인 경우만, 간략히)
3. 신뢰도: 0.0~1.0 사이의 값

JSON 형식으로 답변:
[
  {{
    "item_number": 1,
    "result": "YES" or "NO",
    "evidence": "근거 텍스트" or null,
    "confidence": 0.95
  }},
  ...
]
"""
        
        response = self.llm_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "당신은 계약서 검증 전문가입니다. 체크리스트 항목이 계약서에 충족되는지 정확하게 판단해주세요."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        # 응답 파싱
        llm_results = json.loads(response.choices[0].message.content)
        
        # 결과 매핑
        results = []
        for idx, item in enumerate(checklist_items):
            llm_result = llm_results[idx]
            
            results.append({
                "check_text": item['check_text'],
                "reference": item['reference'],
                "std_global_id": item['global_id'],
                "result": llm_result['result'],
                "evidence": llm_result.get('evidence'),
                "confidence": llm_result['confidence']
            })
        
        return results
    
    def verify_single(
        self,
        user_clause_text: str,
        checklist_item: Dict
    ) -> Dict:
        """
        단일 체크리스트 항목 검증 (폴백용)
        """
        prompt = f"""
다음 계약서 조항이 이 요구사항을 충족하는가?

[계약서 조항]
{user_clause_text}

[요구사항]
{checklist_item['check_text']}

YES 또는 NO로 답변하고, 판단 근거를 제시해주세요.
신뢰도(0.0~1.0)도 함께 제공해주세요.

JSON 형식:
{{
  "result": "YES" or "NO",
  "evidence": "근거" or null,
  "confidence": 0.95
}}
"""
        
        response = self.llm_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "당신은 계약서 검증 전문가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        llm_result = json.loads(response.choices[0].message.content)
        
        return {
            "check_text": checklist_item['check_text'],
            "reference": checklist_item['reference'],
            "std_global_id": checklist_item['global_id'],
            "result": llm_result['result'],
            "evidence": llm_result.get('evidence'),
            "confidence": llm_result['confidence']
        }
```

### ChecklistCheckNode

**역할**: A2 노드 메인 오케스트레이터

```python
class ChecklistCheckNode:
    """A2 노드: 체크리스트 검증"""
    
    def __init__(self, db_session, llm_client):
        self.db = db_session
        self.checklist_loader = ChecklistLoader()
        self.verifier = ChecklistVerifier(llm_client)
    
    def check_checklist(self, contract_id: str) -> Dict:
        """
        체크리스트 검증 메인 함수
        
        Args:
            contract_id: 계약서 ID
            
        Returns:
            검증 결과 딕셔너리
        """
        start_time = time.time()
        
        # 1. A1 매칭 결과 로드
        a1_results = self._load_a1_results(contract_id)
        if not a1_results:
            raise ValueError("A1 매칭 결과가 없습니다")
        
        matching_details = a1_results.get('matching_details', [])
        contract_type = a1_results.get('contract_type')
        
        # 2. 체크리스트 로드
        all_checklists = self.checklist_loader.load_checklist(contract_type)
        
        # 3. 사용자 조항별 검증
        user_article_results = []
        
        for detail in matching_details:
            if not detail.get('matched', False):
                continue
            
            # 사용자 조항 정보
            user_article_no = detail['user_article_no']
            user_article_id = detail['user_article_id']
            user_article_title = detail['user_article_title']
            
            # 매칭된 표준 조항 global_id
            matched_global_ids = detail.get('matched_articles_global_ids', [])
            
            # 관련 체크리스트 필터링
            relevant_checklists = self.checklist_loader.filter_by_global_ids(
                all_checklists,
                matched_global_ids
            )
            
            if not relevant_checklists:
                logger.info(f"조항 {user_article_no}: 체크리스트 없음")
                continue
            
            # 사용자 조항 텍스트 로드
            user_clause_text = self._get_user_clause_text(contract_id, user_article_id)
            
            # LLM 검증
            logger.info(f"조항 {user_article_no}: {len(relevant_checklists)}개 항목 검증 중...")
            checklist_results = self.verifier.verify_batch(
                user_clause_text,
                relevant_checklists
            )
            
            user_article_results.append({
                "user_article_no": user_article_no,
                "user_article_id": user_article_id,
                "user_article_title": user_article_title,
                "matched_std_global_ids": matched_global_ids,
                "checklist_results": checklist_results
            })
        
        # 4. 통계 계산
        statistics = self._calculate_statistics(user_article_results)
        
        # 5. 최종 결과 구성
        processing_time = time.time() - start_time
        
        result = {
            **statistics,
            "user_article_results": user_article_results,
            "processing_time": processing_time,
            "verification_date": datetime.now().isoformat()
        }
        
        # 6. DB 저장
        self._save_to_db(contract_id, result)
        
        return result
    
    def _load_a1_results(self, contract_id: str) -> Dict:
        """
        A1 매칭 결과 및 계약 유형 로드
        
        Args:
            contract_id: 계약서 ID
            
        Returns:
            {
                "matching_details": [...],
                "contract_type": str  # 필수
            }
            
        Raises:
            ValueError: A1 결과 또는 계약 유형이 없는 경우
        """
        # ValidationResult에서 A1 결과 조회
        validation_result = self.db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation_result or not validation_result.completeness_check:
            raise ValueError(f"A1 매칭 결과가 없습니다: {contract_id}")
        
        completeness_check = validation_result.completeness_check
        
        # ClassificationResult에서 계약 유형 조회
        classification = self.db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()
        
        if not classification or not classification.confirmed_type:
            raise ValueError(f"계약 유형이 확정되지 않았습니다: {contract_id}")
        
        contract_type = classification.confirmed_type
        
        # 유효한 계약 유형인지 검증
        valid_types = ['provide', 'create', 'process', 'brokerage_provider', 'brokerage_user']
        if contract_type not in valid_types:
            raise ValueError(f"지원하지 않는 계약 유형: {contract_type}")
        
        logger.info(f"A1 결과 로드 완료: {contract_id}, 계약 유형: {contract_type}")
        
        return {
            **completeness_check,
            "contract_type": contract_type
        }
    
    def _get_user_clause_text(self, contract_id: str, user_article_id: str) -> str:
        """사용자 조항 텍스트 로드"""
        contract = self.db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        parsed_data = contract.parsed_data
        articles = parsed_data.get('articles', [])
        
        for article in articles:
            if article.get('article_id') == user_article_id:
                # 제목 + 내용 결합
                title = article.get('text', '')
                content_items = article.get('content', [])
                content = '\n'.join(content_items)
                
                return f"{title}\n{content}"
        
        return ""
    
    def _calculate_statistics(self, user_article_results: List[Dict]) -> Dict:
        """통계 계산"""
        total_items = 0
        verified_items = 0
        passed_items = 0
        failed_items = 0
        
        for result in user_article_results:
            checklist_results = result.get('checklist_results', [])
            
            for item in checklist_results:
                total_items += 1
                verified_items += 1
                
                if item['result'] == 'YES':
                    passed_items += 1
                else:
                    failed_items += 1
        
        return {
            "total_checklist_items": total_items,
            "verified_items": verified_items,
            "passed_items": passed_items,
            "failed_items": failed_items
        }
    
    def _save_to_db(self, contract_id: str, result: Dict):
        """DB 저장"""
        validation_result = self.db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation_result:
            validation_result = ValidationResult(contract_id=contract_id)
            self.db.add(validation_result)
        
        validation_result.checklist_validation = result
        self.db.commit()
```

## 데이터 플로우

### 입력 데이터

**A1 매칭 결과 (ValidationResult.completeness_check)**
```json
{
    "matching_details": [
        {
            "user_article_no": 1,
            "user_article_id": "user_article_001",
            "user_article_title": "목적",
            "matched": true,
            "matched_articles_global_ids": ["urn:std:brokerage_provider:art:001"]
        }
    ]
}
```

**체크리스트 데이터 (JSON 파일)**
```json
[
    {
        "check_text": "개인의 경우 이름, 법인의 경우 상호 등이 기재되어 있는가?",
        "reference": "제1조 (106쪽)",
        "global_id": "urn:std:brokerage_provider:art:001"
    }
]
```

### 출력 데이터

**ValidationResult.checklist_validation**
```json
{
    "total_checklist_items": 45,
    "verified_items": 42,
    "passed_items": 35,
    "failed_items": 7,
    "user_article_results": [
        {
            "user_article_no": 1,
            "user_article_id": "user_article_001",
            "user_article_title": "목적",
            "matched_std_global_ids": ["urn:std:brokerage_provider:art:001"],
            "checklist_results": [
                {
                    "check_text": "개인의 경우 이름, 법인의 경우 상호 등이 기재되어 있는가?",
                    "reference": "제1조 (106쪽)",
                    "std_global_id": "urn:std:brokerage_provider:art:001",
                    "result": "YES",
                    "evidence": "제1조에서 '갑: 주식회사 데이터허브(대표이사 홍길동)' 명시",
                    "confidence": 0.95
                }
            ]
        }
    ],
    "processing_time": 12.5,
    "verification_date": "2025-01-01T00:00:00Z"
}
```

## 에러 처리

### A1 결과 없음

```python
a1_results = self._load_a1_results(contract_id)
if not a1_results:
    raise ValueError(f"A1 매칭 결과가 없습니다: {contract_id}")
```

### 체크리스트 파일 없음

```python
try:
    checklist_data = self.checklist_loader.load_checklist(contract_type)
except FileNotFoundError:
    logger.error(f"체크리스트 파일 없음: {contract_type}")
    raise ValueError(f"체크리스트 파일을 찾을 수 없습니다: {contract_type}")
```

### LLM 호출 실패

```python
try:
    batch_results = self._verify_batch_llm(user_clause_text, batch)
except Exception as e:
    logger.error(f"배치 검증 실패: {e}, 개별 검증으로 폴백")
    # 개별 검증으로 폴백
    for item in batch:
        try:
            result = self.verify_single(user_clause_text, item)
            results.append(result)
        except Exception as e2:
            logger.error(f"개별 검증도 실패: {e2}, 항목 건너뜀")
            continue
```

### DB 저장 실패

```python
try:
    self._save_to_db(contract_id, result)
except Exception as e:
    logger.error(f"DB 저장 실패: {e}")
    # 재시도 또는 에러 전파
    raise
```

## 성능 최적화

### 배치 처리

- 한 조항의 여러 체크리스트를 한 번의 LLM 호출로 처리
- 기본 배치 크기: 10개
- API 호출 횟수 최대 90% 감소

### 캐싱

```python
# 체크리스트 데이터 캐싱
self._cache = {}  # 계약 유형별

# 한 번 로드하면 메모리에 유지
if contract_type in self._cache:
    return self._cache[contract_type]
```

### 병렬 처리 (향후)

```python
# 여러 조항을 병렬로 처리
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=3) as executor:
    futures = []
    for detail in matching_details:
        future = executor.submit(self._verify_article, detail)
        futures.append(future)
    
    results = [f.result() for f in futures]
```

## 테스트 전략

### 단위 테스트

1. **ChecklistLoader**
   - JSON 파일 로드
   - global_id 필터링
   - 중복 제거

2. **ChecklistVerifier**
   - LLM 프롬프트 생성
   - 응답 파싱
   - 배치 처리

3. **ChecklistCheckNode**
   - A1 결과 로드
   - 통계 계산
   - DB 저장

### 통합 테스트

1. **전체 플로우**
   - A1 결과 → A2 검증 → DB 저장
   - 여러 조항 처리
   - 에러 처리

2. **LLM 통합**
   - 실제 LLM 호출
   - 응답 형식 검증
   - 타임아웃 처리

### E2E 테스트

1. **실제 계약서**
   - 업로드 → 분류 → A1 → A2
   - 결과 확인
   - 프론트엔드 표시

## 프론트엔드 통합

### API 엔드포인트

```python
# FastAPI
@app.get("/api/validation/{contract_id}")
def get_validation_result(contract_id: str):
    """검증 결과 조회 (A1, A2, A3 포함)"""
    validation_result = db.query(ValidationResult).filter(
        ValidationResult.contract_id == contract_id
    ).first()
    
    return {
        "completeness_check": validation_result.completeness_check,
        "checklist_validation": validation_result.checklist_validation,
        "content_analysis": validation_result.content_analysis
    }
```

### 프론트엔드 표시

```python
# Streamlit (frontend/app.py)
def display_checklist_results(checklist_validation: Dict):
    """체크리스트 결과 표시"""
    
    # 토글 버튼
    if st.button("📋 체크리스트 검증 결과 보기"):
        st.session_state.show_checklist = not st.session_state.get('show_checklist', False)
    
    if st.session_state.get('show_checklist', False):
        # 통계
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("전체 항목", f"{checklist_validation['total_checklist_items']}개")
        with col2:
            st.metric("통과", f"{checklist_validation['passed_items']}개")
        with col3:
            st.metric("미충족", f"{checklist_validation['failed_items']}개")
        
        # 조항별 결과
        for result in checklist_validation['user_article_results']:
            st.markdown(f"#### 제{result['user_article_no']}조 {result['user_article_title']}")
            
            for item in result['checklist_results']:
                if item['result'] == 'YES':
                    st.success(f"✅ {item['check_text']}")
                    if item['evidence']:
                        st.caption(f"근거: {item['evidence']}")
                else:
                    st.error(f"❌ {item['check_text']}")
                    st.caption("해당 내용이 계약서에 명시되지 않았습니다.")
```

## 신뢰도 기반 재검증 로직

### 개요

1차 검증에서 신뢰도가 낮을 경우 (< 0.7), 표준 조항 컨텍스트를 추가하여 재검증을 수행합니다. 재검증 후에도 신뢰도가 낮으면 "UNCLEAR" 상태로 표시하여 수동 검토를 요청합니다.

### 처리 플로우

```
1. 1차 검증 (사용자 조항 + 체크리스트)
   ↓
2. 신뢰도 확인
   ↓
3-A. 신뢰도 >= 0.7 → 결과 반환
   ↓
3-B. 신뢰도 < 0.7 → 재검증 시작
   ↓
4. 표준 조항 로드 (global_id 기반)
   ↓
5. 2차 검증 (사용자 조항 + 표준 조항 + 체크리스트)
   ↓
6. 재검증 신뢰도 확인
   ↓
7-A. 신뢰도 >= 0.7 → 결과 반환
   ↓
7-B. 신뢰도 < 0.7 → UNCLEAR 처리
```

### 구현

```python
class ChecklistVerifier:
    """LLM 기반 체크리스트 검증기"""
    
    CONFIDENCE_THRESHOLD = 0.7  # 신뢰도 임계값
    
    def verify_with_low_confidence_handling(
        self,
        user_clause_text: str,
        checklist_item: Dict,
        contract_type: str,
        kb_loader
    ) -> Dict:
        """
        신뢰도 기반 재검증 로직
        
        Args:
            user_clause_text: 사용자 조항 텍스트
            checklist_item: 체크리스트 항목
            contract_type: 계약 유형
            kb_loader: 지식베이스 로더 (표준 조항 로드용)
            
        Returns:
            검증 결과 (result, evidence, confidence, requires_manual_review)
        """
        # 1차 검증
        result = self.verify_single(user_clause_text, checklist_item)
        
        # 신뢰도 충분하면 바로 반환
        if result['confidence'] >= self.CONFIDENCE_THRESHOLD:
            result['requires_manual_review'] = False
            return result
        
        logger.warning(
            f"신뢰도 낮음 ({result['confidence']:.2f}), "
            f"체크리스트: {checklist_item['check_text'][:50]}..."
        )
        
        # 표준 조항 로드 및 재검증
        try:
            std_clause_text = self._load_std_clause(
                checklist_item['std_global_id'],
                contract_type,
                kb_loader
            )
            
            logger.info("표준 조항 컨텍스트 추가하여 재검증 시작")
            
            # 2차 검증 (컨텍스트 추가)
            result_v2 = self.verify_with_context(
                user_clause_text,
                std_clause_text,
                checklist_item
            )
            
            logger.info(f"재검증 완료: 신뢰도 {result_v2['confidence']:.2f}")
            
            # 재검증 후에도 신뢰도 낮으면 UNCLEAR 처리
            if result_v2['confidence'] < self.CONFIDENCE_THRESHOLD:
                logger.warning(f"재검증 후에도 신뢰도 낮음, UNCLEAR 처리")
                result_v2['result'] = "UNCLEAR"
                result_v2['requires_manual_review'] = True
            else:
                result_v2['requires_manual_review'] = False
            
            return result_v2
            
        except Exception as e:
            logger.error(f"재검증 실패: {e}, 1차 검증 결과 사용")
            # 재검증 실패 시 1차 결과 사용 (UNCLEAR 처리)
            result['result'] = "UNCLEAR"
            result['requires_manual_review'] = True
            result['evidence'] = f"재검증 실패: {str(e)}"
            return result
    
    def verify_with_context(
        self,
        user_clause_text: str,
        std_clause_text: str,
        checklist_item: Dict
    ) -> Dict:
        """
        표준 조항 컨텍스트를 포함한 검증
        
        Args:
            user_clause_text: 사용자 조항 텍스트
            std_clause_text: 표준 조항 텍스트
            checklist_item: 체크리스트 항목
            
        Returns:
            검증 결과
        """
        prompt = f"""
다음 사용자 계약서 조항이 체크리스트 요구사항을 충족하는지 검증해주세요.

[사용자 계약서 조항]
{user_clause_text}

[참고: 표준계약서 조항]
{std_clause_text}

[체크리스트 요구사항]
{checklist_item['check_text']}

표준계약서를 참고하여 더 정확히 판단해주세요.
사용자 조항이 표준과 완전히 동일하지 않아도, 의미적으로 유사하면 YES로 판단할 수 있습니다.

JSON 형식으로 답변:
{{
  "result": "YES" or "NO",
  "evidence": "판단 근거" or null,
  "confidence": 0.95
}}
"""
        
        response = self.llm_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "당신은 계약서 검증 전문가입니다. 표준계약서를 참고하여 정확하게 판단해주세요."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        llm_result = json.loads(response.choices[0].message.content)
        
        return {
            "check_text": checklist_item['check_text'],
            "reference": checklist_item['reference'],
            "std_global_id": checklist_item['global_id'],
            "result": llm_result['result'],
            "evidence": llm_result.get('evidence'),
            "confidence": llm_result['confidence']
        }
    
    def _load_std_clause(
        self,
        std_global_id: str,
        contract_type: str,
        kb_loader
    ) -> str:
        """
        표준 조항 텍스트 로드
        
        Args:
            std_global_id: 표준 조항 global_id
            contract_type: 계약 유형
            kb_loader: 지식베이스 로더
            
        Returns:
            표준 조항 전문 (제목 + 내용)
        """
        # 지식베이스에서 청크 로드
        chunks = kb_loader.load_chunks(contract_type)
        
        # global_id가 일치하는 청크들 수집
        matched_chunks = []
        for chunk in chunks:
            chunk_global_id = chunk.get('global_id', '')
            # base global_id 추출 (예: urn:std:provide:art:001)
            base_id = ':'.join(chunk_global_id.split(':')[:5])
            
            if base_id == std_global_id:
                matched_chunks.append(chunk)
        
        if not matched_chunks:
            raise ValueError(f"표준 조항을 찾을 수 없습니다: {std_global_id}")
        
        # 제목 + 내용 결합
        title = matched_chunks[0].get('title', '')
        parent_id = matched_chunks[0].get('parent_id', '')
        
        content_parts = []
        for chunk in matched_chunks:
            text = chunk.get('text_raw', chunk.get('text', ''))
            if text:
                content_parts.append(text)
        
        content = '\n'.join(content_parts)
        
        return f"{parent_id} {title}\n{content}"
```

## 향후 개선 사항

### 1. 부분 매칭 지원 (PARTIAL 상태)

```python
# YES/NO/UNCLEAR 외에 PARTIAL 상태 추가
{
    "result": "PARTIAL",
    "evidence": "일부 내용만 포함",
    "missing_elements": ["구체적 기간", "책임 범위"],
    "confidence": 0.75
}
```

### 2. 사용자 피드백 통합

```python
# 사용자가 결과 수정 가능
{
    "result": "NO",
    "user_override": "YES",
    "user_comment": "실제로는 제5조에 포함되어 있음"
}
```

### 3. 우선순위 기반 검증

```python
# 체크리스트에 우선순위 추가
{
    "check_text": "...",
    "priority": "high",  # high, medium, low
    "required": true
}

# 필수 항목만 먼저 검증
```
