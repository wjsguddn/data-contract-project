# 병렬 처리 아키텍처

## 전체 시스템 플로우

```mermaid
graph TB
    Start[사용자 계약서 업로드] --> Parse[DOCX 파싱]
    Parse --> Classify[Classification Agent]
    Classify --> Confirm{사용자 확인}
    Confirm -->|확인| Validation[Consistency Agent]
    
    subgraph "Consistency Agent - 병렬 처리"
        Validation --> A1_Stage1[A1 Stage 1: 조항 매칭]
        
        A1_Stage1 --> Parallel{병렬 실행}
        
        Parallel -->|Thread 1| A1_Stage2[A1 Stage 2: LLM 재검증]
        Parallel -->|Thread 2| A2[A2: 체크리스트 검증]
        Parallel -->|Thread 3| A3[A3: 내용 분석]
        
        A1_Stage2 --> Merge[결과 병합]
        A2 --> Merge
        A3 --> Merge
    end
    
    Merge --> Report[Report Agent]
    
    subgraph "Report Agent - 순차 처리"
        Report --> Step1[Step1: 정규화]
        Step1 --> Step2[Step2: 집계]
        Step2 --> Step3[Step3: 충돌 해소]
        Step3 --> Step4[Step4: 포맷팅]
        Step4 --> Step5[Step5: 종합분석 생성]
    end
    
    Step5 --> Display[보고서 표시]
```


## Consistency Agent 상세 병렬 구조

```mermaid
sequenceDiagram
    participant User as 사용자
    participant API as FastAPI
    participant Celery as Celery Queue
    participant A1 as A1 Worker
    participant A2 as A2 Worker
    participant A3 as A3 Worker
    participant DB as Database
    
    User->>API: 검증 시작 요청
    API->>Celery: validate_contract_task
    
    Note over Celery,A1: Stage 1: 조항 매칭 (순차)
    Celery->>A1: A1 Stage 1 실행
    A1->>A1: 하이브리드 검색으로 조항 매칭
    A1->>DB: A1 Stage 1 결과 저장
    
    Note over A1,A3: Stage 2: 병렬 처리 시작
    
    par A1 Stage 2
        A1->>A1: LLM으로 매칭 재검증
        A1->>DB: A1 Stage 2 결과 저장
    and A2 검증
        Celery->>A2: A2 체크리스트 검증
        A2->>A2: 활용안내서 기반 검증
        A2->>DB: A2 결과 저장
    and A3 분석
        Celery->>A3: A3 내용 분석
        A3->>A3: 조항별 충실도 평가
        A3->>DB: A3 결과 저장
    end
    
    Note over Celery: 모든 작업 완료 대기
    
    DB->>API: 통합 결과 조회
    API->>User: 검증 완료
```


## Report Agent 데이터 처리 플로우

```mermaid
graph LR
    subgraph "입력 데이터"
        A1_Result[A1 결과]
        A2_Result[A2 결과]
        A3_Result[A3 결과]
        User_Contract[사용자 계약서]
    end
    
    subgraph "Step 1: 정규화"
        A1_Result --> Normalize
        A3_Result --> Normalize
        Normalize[데이터 정규화]
        Normalize --> |조 단위 정리| Step1_Out[정규화된 데이터]
    end
    
    subgraph "Step 2: 집계"
        Step1_Out --> Aggregate[항 단위 집계]
        Aggregate --> |충돌 감지| Step2_Out[집계된 데이터]
    end
    
    subgraph "Step 3: 충돌 해소"
        Step2_Out --> Resolve[규칙 + LLM 해소]
        User_Contract --> Resolve
        Resolve --> Step3_Out[해소된 데이터]
    end
    
    subgraph "Step 4: 포맷팅"
        Step3_Out --> Format[제목 추가 등]
        Format --> Step4_Out[포맷된 데이터]
    end
    
    subgraph "Step 5: 종합분석"
        Step4_Out --> Integrate
        A2_Result --> Integrate[체크리스트 통합]
        User_Contract --> Integrate
        Integrate --> |LLM 생성| Final[최종 보고서]
    end
```


## 병렬 처리 성능 비교

```mermaid
gantt
    title 순차 처리 vs 병렬 처리 시간 비교
    dateFormat X
    axisFormat %s초
    
    section 순차 처리
    A1 Stage 1 (30초)    :0, 30
    A1 Stage 2 (60초)    :30, 90
    A2 검증 (45초)       :90, 135
    A3 분석 (50초)       :135, 185
    
    section 병렬 처리
    A1 Stage 1 (30초)    :0, 30
    A1 Stage 2 (60초)    :30, 90
    A2 검증 (45초)       :30, 75
    A3 분석 (50초)       :30, 80
```

### 성능 개선

- **순차 처리**: 약 185초 (3분 5초)
- **병렬 처리**: 약 90초 (1분 30초)
- **개선율**: 51% 시간 단축

## 주요 특징

### 1. Celery 기반 비동기 처리
- Redis를 메시지 브로커로 사용
- 각 Agent는 독립적인 Worker로 실행
- 작업 큐를 통한 느슨한 결합

### 2. 병렬 처리 전략
- A1 Stage 1 완료 후 Stage 2, A2, A3 동시 실행
- 각 작업은 독립적으로 DB에 결과 저장
- Report Agent에서 통합 처리

### 3. 에러 처리
- 각 작업은 독립적으로 실패 가능
- 일부 실패해도 다른 작업 계속 진행
- 최종 보고서에서 누락된 데이터 표시

### 4. 확장성
- Worker 수 증가로 처리량 향상 가능
- 각 Agent별 독립적인 스케일링
- Docker Compose로 간편한 배포
