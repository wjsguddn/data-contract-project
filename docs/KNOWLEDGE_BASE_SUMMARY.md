# 지식베이스 구축 3줄 요약 (PPT용)

## 핵심 요약

1. **문서 파싱 및 구조화**: 표준계약서 5종과 활용안내서를 조/항/호 단위로 분석하여 구조화된 JSON 데이터로 변환

2. **청킹 및 임베딩**: 구조화된 데이터를 항/호 단위로 분할하고, Azure OpenAI를 통해 3072차원 벡터로 임베딩 생성

3. **하이브리드 검색 인덱스 구축**: FAISS(벡터 검색)와 Whoosh(키워드 검색) 인덱스를 생성하여 의미 기반 + 키워드 기반 하이브리드 검색 지원

---

## 상세 설명 (필요시)

### 1단계: 파싱 (Parsing)
- **입력**: PDF/DOCX 원본 문서
- **처리**: 문서 구조 분석 (조, 항, 호 추출)
- **출력**: `*_structured.json` (구조화된 데이터)

### 2단계: 청킹 (Chunking)
구조화된 계약서 데이터를 검색에 최적화된 작은 단위로 분할합니다. 각 조항의 항과 호를 개별 청크로 나누고, 계약서 유형, 조 번호, 항 번호 등의 메타데이터를 함께 저장합니다. 이렇게 생성된 청크 데이터는 JSON 파일로 저장되어 다음 단계의 입력으로 사용됩니다.

### 3단계: 임베딩 (Embedding)
분할된 청크의 텍스트를 Azure OpenAI API에 전송하여 의미를 담은 수치 벡터로 변환합니다. 각 청크는 3072개의 숫자로 이루어진 벡터로 표현되며, 이를 통해 텍스트의 의미적 유사도를 수학적으로 계산할 수 있게 됩니다. 이 벡터들은 이후 유사한 내용을 빠르게 찾는 데 활용됩니다.

### 4단계: 인덱싱 (Indexing)
생성된 벡터와 원본 텍스트를 두 가지 방식으로 인덱싱합니다. FAISS는 벡터 간 유사도를 계산하여 의미가 비슷한 조항을 찾아내고, Whoosh는 BM25 알고리즘으로 키워드 매칭을 수행합니다. 두 인덱스를 함께 사용하는 하이브리드 검색을 통해 의미 기반 검색과 키워드 기반 검색의 장점을 모두 활용할 수 있습니다.

---

## 기술 스택

| 구성 요소 | 기술 |
|---------|------|
| 문서 파싱 | PyMuPDF (PDF), python-docx (DOCX) |
| 임베딩 | Azure OpenAI (text-embedding-3-large) |
| 벡터 검색 | FAISS (IndexFlatIP) |
| 키워드 검색 | Whoosh (BM25) |
| 실행 환경 | Docker, Python 3.10+ |

---

## 데이터 플로우

```
원본 문서 (PDF/DOCX)
    ↓
파싱 (구조 추출)
    ↓
청킹 (항/호 분할)
    ↓
임베딩 (벡터 생성)
    ↓
인덱싱 (FAISS + Whoosh)
    ↓
검색 가능한 지식베이스
```

---

## 활용

- **Classification Agent**: 사용자 계약서 유형 분류
- **Consistency Agent A1**: 표준계약서 조항 매칭
- **Consistency Agent A2**: 체크리스트 항목 검증
- **Report Agent**: 분석 보고서 생성

---

## 실행 명령어

```bash
# Docker 환경에서 전체 파이프라인 실행
docker-compose -f docker/docker-compose.yml --profile ingestion run --rm ingestion

# CLI에서 대화형 실행
python -m ingestion.ingest
> run --mode full --file all
```
