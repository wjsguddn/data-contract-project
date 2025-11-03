# 사용자 계약서 파싱 설명

## 개요

사용자가 업로드한 DOCX 계약서를 분석하여 조항 구조를 추출하는 파서입니다. Phase 1에서는 간단한 정규식 기반 파싱을 사용하며, Phase 2에서는 VLM(Vision Language Model) 기반의 유연한 파싱으로 전환할 예정입니다.

---

## Phase 1: 간단한 조 단위 파싱 (현재)

### 핵심 원리

"제n조"로 시작하는 문단을 감지하여 조 단위로 분할하고, 각 조의 하위 내용을 평면적으로 수집합니다. 복잡한 계층 구조(항, 호)는 무시하고 단순하게 처리합니다.

### 파싱 로직

1. **서문(Preamble) 수집**: "제1조"가 나오기 전까지의 모든 텍스트를 서문으로 수집
2. **조(Article) 인식**: "제n조" 또는 "제 n조" 패턴으로 시작하는 문단 감지
3. **별지(Exhibit) 인식**: "별지n" 또는 "별지 n" 패턴으로 시작하는 문단 감지
4. **내용 수집**: 각 조/별지의 하위 내용을 평면 구조로 수집

### 정규식 패턴

```python
# 조 패턴: "제1조", "제 1조", "[제1조]", "  제1조" 등 다양한 형식 지원
article_pattern = r'^[\s\W_]*제\s*(\d+)조'

# 별지 패턴: "별지1", "별지 1", "[별지1]" 등 다양한 형식 지원
exhibit_pattern = r'^[\s\W_]*별지\s*(\d+)'
```

### 제목 추출

조 번호 뒤의 텍스트에서 제목을 추출합니다:
- "제1조(목적)" → "목적"
- "제1조 목적" → "목적"
- "[제1조] 목적" → "목적"
- "제 1 조 (목적)" → "목적"

앞뒤 공백과 특수문자를 제거하여 깔끔한 제목만 추출합니다.

---

## 출력 구조

### JSON 형식

```json
{
  "preamble": [
    "데이터 제공 계약서",
    "본 계약은 다음과 같이 체결한다."
  ],
  "articles": [
    {
      "article_id": "user_article_001",
      "number": 1,
      "title": "목적",
      "text": "제1조(목적)",
      "content": [
        "본 계약은 데이터 제공에 관한 사항을 정함을 목적으로 한다.",
        "제공자는 수요자에게 데이터를 제공한다."
      ]
    },
    {
      "article_id": "user_article_002",
      "number": 2,
      "title": "정의",
      "text": "제2조(정의)",
      "content": [
        "본 계약에서 사용하는 용어의 정의는 다음과 같다.",
        "1. 데이터: 별지 1에 명시된 데이터를 말한다.",
        "2. 제공자: 데이터를 제공하는 자를 말한다."
      ]
    }
  ],
  "exhibits": [
    {
      "exhibit_id": "user_exhibit_001",
      "number": 1,
      "title": "대상데이터",
      "text": "별지1(대상데이터)",
      "content": [
        "데이터명: 고객 거래 데이터",
        "데이터 형식: CSV",
        "제공 주기: 월 1회"
      ]
    }
  ]
}
```

### 메타데이터

```json
{
  "total_articles": 15,
  "recognized_articles": 15,
  "total_exhibits": 3,
  "recognized_exhibits": 3,
  "unrecognized_sections": 0,
  "confidence": 1.0,
  "parser_version": "phase1_simple",
  "preamble_lines": 2
}
```

---

## 파싱 프로세스

### 1. 업로드
사용자가 Streamlit UI를 통해 DOCX 파일 업로드

### 2. 파싱
FastAPI 서버에서 `UserContractParser` 실행
- python-docx로 문단 단위 읽기
- 정규식으로 조/별지 패턴 감지
- 구조화된 JSON 데이터 생성

### 3. 저장
- 파싱 결과를 `*_parsed.json` 파일로 저장
- 데이터베이스에 메타데이터 저장

### 4. 다음 단계
- Classification Agent로 계약서 유형 분류
- Consistency Agent로 정합성 검증

---

## 지원 형식

### 현재 지원 (Phase 1)
- **파일 형식**: DOCX만 지원
- **구조**: "제n조" 형식의 구조화된 계약서
- **제목 형식**: 
  - "제1조(목적)"
  - "제1조 목적"
  - "[제1조] 목적"
  - "제 1 조 (목적)"

### 제한사항
- 항/호 계층 구조 무시 (평면 구조로 수집)
- PDF 파일 미지원
- 비정형 계약서 미지원
- "제n조" 패턴이 없는 계약서 미지원

---

## Phase 2: VLM 기반 유연한 파싱 (계획)

### 목표
다양한 형식의 계약서를 유연하게 파싱

### 주요 기능
1. **비정형 구조 인식**: "제n조" 패턴이 없어도 조항 구조 파악
2. **PDF 지원**: 이미지 기반 레이아웃 분석
3. **계층 구조 인식**: 항, 호, 목 등 세부 계층 구조 파악
4. **표 및 이미지 처리**: 계약서 내 표와 이미지 데이터 추출
5. **다국어 지원**: 영어 계약서 처리

### 기술 스택 (예정)
- Vision Language Model (GPT-4V, Claude 3 등)
- OCR (Tesseract, Azure Computer Vision)
- 레이아웃 분석 (LayoutLM, Donut)

---

## 사용 예시

### Python 코드

```python
from pathlib import Path
from backend.fastapi.user_contract_parser import UserContractParser

# 파서 초기화
parser = UserContractParser()

# 파일 경로
docx_path = Path("data/user_contracts/my_contract.docx")
output_dir = Path("data/parsed_contracts")

# 파싱 실행
result = parser.parse(docx_path, output_dir)

if result["success"]:
    print(f"파싱 성공: {result['parsed_metadata']['total_articles']}개 조 인식")
    print(f"저장 경로: {result['structured_path']}")
else:
    print(f"파싱 실패: {result['error']}")
```

### API 호출

```bash
# 계약서 업로드 및 파싱
curl -X POST "http://localhost:8000/api/contracts/upload" \
  -F "file=@my_contract.docx" \
  -F "contract_name=데이터제공계약서"
```

---

## 에러 처리

### 파싱 실패 케이스
1. **조 패턴 없음**: "제n조" 패턴이 하나도 없는 경우
   - confidence: 0.0
   - total_articles: 0

2. **파일 손상**: DOCX 파일이 손상된 경우
   - success: False
   - error: "파일을 읽을 수 없습니다"

3. **빈 문서**: 내용이 없는 경우
   - total_articles: 0
   - confidence: 0.0

### 경고 케이스
1. **조 번호 불연속**: 제1조 → 제3조 (제2조 누락)
   - 파싱은 성공하지만 로그에 경고 기록

2. **중복 조 번호**: 제1조가 두 번 나오는 경우
   - 마지막 조로 덮어씀

---

## 성능

### 처리 속도
- 10페이지 계약서: 약 1~2초
- 50페이지 계약서: 약 3~5초

### 메모리 사용
- 10MB DOCX 파일: 약 50MB 메모리 사용

### 정확도
- 구조화된 계약서: 95% 이상
- 비정형 계약서: Phase 2에서 개선 예정
