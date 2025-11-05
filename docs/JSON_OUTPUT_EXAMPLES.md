# Consistency Agent JSON 출력 예시

## 개요

A1, A2, A3 각 노드의 JSON 출력 구조와 실제 예시를 보여줍니다.

---

## A1 Node: 조항 매칭 결과

### 목적
사용자 계약서와 표준계약서의 조항을 매칭한 결과 (1:N 매칭 가능)

### JSON 구조

```json
{
  "contract_id": "user_contract_20241104_001",
  "std_contract_type": "provide_std_contract",
  "matching_timestamp": "2024-11-04T10:30:00Z",
  "summary": {
    "total_user_articles": 15,
    "matched_articles": 12,
    "unmatched_user_articles": 3,
    "unmapped_std_articles": 5,
    "average_confidence": 0.82
  },
  "article_mappings": [
    {
      "user_article_id": "제3조",
      "user_article_title": "개인정보의 수집",
      "user_article_items": [
        {
          "item_id": "제3조 제1항",
          "content": "개인정보처리자는 개인정보를 수집하는 경우 그 목적에 필요한 최소한의 개인정보를 수집하여야 한다."
        },
        {
          "item_id": "제3조 제2항",
          "content": "수집하는 개인정보의 항목은 다음과 같다: 성명, 연락처, 이메일 주소"
        },
        {
          "item_id": "제3조 제3항",
          "content": "개인정보의 수집 방법은 서면, 전화, 이메일, 웹사이트를 통한 방법으로 한다."
        }
      ],
      "matched_std_articles": [
        {
          "std_article_id": "제5조",
          "std_article_title": "개인정보의 수집 및 이용",
          "confidence_score": 0.87,
          "num_matched_items": 3,
          "llm_verified": true,
          "verification_reason": "두 조항 모두 개인정보 수집의 원칙과 방법을 다루고 있으며, 최소 수집 원칙이 명시되어 있음"
        }
      ],
      "matching_details": {
        "item_level_matches": [
          {
            "user_item_id": "제3조 제1항",
            "matched_std_item_id": "제5조 제2항",
            "semantic_score": 0.89,
            "keyword_score": 0.85,
            "hybrid_score": 0.87
          },
          {
            "user_item_id": "제3조 제2항",
            "matched_std_item_id": "제5조 제3항",
            "semantic_score": 0.82,
            "keyword_score": 0.88,
            "hybrid_score": 0.85
          },
          {
            "user_item_id": "제3조 제3항",
            "matched_std_item_id": "제5조 제4항",
            "semantic_score": 0.91,
            "keyword_score": 0.86,
            "hybrid_score": 0.89
          }
        ],
        "aggregated_article_score": 1.37,
        "normalized_score": 0.87
      },
      "status": "confirmed"
    },
    {
      "user_article_id": "제4조",
      "user_article_title": "개인정보의 이용",
      "user_article_items": [
        {
          "item_id": "제4조 제1항",
          "content": "개인정보처리자는 수집한 개인정보를 명시한 목적 범위 내에서만 이용한다."
        },
        {
          "item_id": "제4조 제2항",
          "content": "목적 외 이용이 필요한 경우 정보주체의 동의를 받아야 한다."
        }
      ],
      "matched_std_articles": [
        {
          "std_article_id": "제6조",
          "std_article_title": "개인정보의 이용 및 목적",
          "confidence_score": 0.91,
          "num_matched_items": 2,
          "llm_verified": true,
          "verification_reason": "개인정보 이용 목적 제한 및 동의 절차가 일치함"
        }
      ],
      "matching_details": {
        "item_level_matches": [
          {
            "user_item_id": "제4조 제1항",
            "matched_std_item_id": "제6조 제1항",
            "semantic_score": 0.93,
            "keyword_score": 0.89,
            "hybrid_score": 0.91
          },
          {
            "user_item_id": "제4조 제2항",
            "matched_std_item_id": "제6조 제2항",
            "semantic_score": 0.90,
            "keyword_score": 0.92,
            "hybrid_score": 0.91
          }
        ],
        "aggregated_article_score": 1.52,
        "normalized_score": 0.91
      },
      "status": "confirmed"
    },
    {
      "user_article_id": "제5조",
      "user_article_title": "개인정보의 제3자 제공",
      "user_article_items": [
        {
          "item_id": "제5조 제1항",
          "content": "개인정보처리자는 정보주체의 동의 없이 개인정보를 제3자에게 제공하지 않는다."
        }
      ],
      "matched_std_articles": [
        {
          "std_article_id": "제7조",
          "std_article_title": "개인정보의 제공",
          "confidence_score": 0.78,
          "num_matched_items": 1,
          "llm_verified": false,
          "verification_reason": "제3자 제공 원칙은 유사하나, 표준계약서는 제공 절차가 더 상세함"
        }
      ],
      "matching_details": {
        "item_level_matches": [
          {
            "user_item_id": "제5조 제1항",
            "matched_std_item_id": "제7조 제1항",
            "semantic_score": 0.80,
            "keyword_score": 0.76,
            "hybrid_score": 0.78
          }
        ],
        "aggregated_article_score": 0.78,
        "normalized_score": 0.78
      },
      "status": "needs_review"
    }
  ],
  "unmatched_user_articles": [
    {
      "user_article_no": 12,
      "user_article_id": "user_article_012",
      "user_article_title": "분쟁 해결",
      "matched": false,
      "reason": "하이브리드 검색 결과 임계값 미달",
      "best_match_score": 0.42,
      "best_match_std_article": "제15조",
      "search_details": {
        "top_candidates": [
          {
            "std_article_id": "제15조",
            "std_article_title": "분쟁 조정",
            "score": 0.42,
            "reason": "점수가 임계값(0.7) 미달"
          },
          {
            "std_article_id": "제16조",
            "std_article_title": "관할 법원",
            "score": 0.38,
            "reason": "점수가 임계값(0.7) 미달"
          }
        ],
        "llm_verification": "검색된 후보 조항들이 모두 낮은 유사도를 보여 매칭 불가 판정"
      }
    },
    {
      "user_article_no": 13,
      "user_article_id": "user_article_013",
      "user_article_title": "특약 사항",
      "matched": false,
      "reason": "표준계약서에 해당 조항 없음 (사용자 추가 조항)",
      "best_match_score": 0.25,
      "best_match_std_article": null,
      "search_details": {
        "top_candidates": [],
        "llm_verification": "표준계약서에 대응되는 조항이 없는 사용자 고유 조항"
      }
    }
  ],
  "unmapped_std_articles": [
    {
      "std_article_id": "urn:std:provide:art:008",
      "std_article_title": "개인정보의 파기",
      "parent_id": "제8조",
      "is_truly_missing": true,
      "confidence": 0.95,
      "reason": "사용자 계약서에 해당 조항 없음 (필수 조항)",
      "reverse_search_result": {
        "searched": true,
        "top_user_candidates": [
          {
            "user_article_no": 7,
            "user_article_title": "개인정보의 보관",
            "similarity": 0.52,
            "reason": "보관 기간만 명시, 파기 절차 없음"
          }
        ],
        "llm_analysis": "사용자 계약서 제7조에서 보관 기간은 언급되었으나, 파기 방법 및 절차에 대한 구체적인 내용이 누락됨"
      },
      "recommendation": "개인정보 파기 방법 및 절차를 명시하는 조항 추가 필요",
      "severity": "high",
      "trigger_a2": true
    },
    {
      "std_article_id": "urn:std:provide:art:009",
      "std_article_title": "정보주체의 권리",
      "parent_id": "제9조",
      "is_truly_missing": false,
      "confidence": 0.82,
      "reason": "사용자 계약서 여러 조항에 분산되어 있음",
      "reverse_search_result": {
        "searched": true,
        "top_user_candidates": [
          {
            "user_article_no": 6,
            "user_article_title": "개인정보 열람 및 정정",
            "similarity": 0.78,
            "reason": "열람권과 정정권은 명시됨"
          },
          {
            "user_article_no": 4,
            "user_article_title": "개인정보의 이용",
            "similarity": 0.65,
            "reason": "동의 철회권 일부 언급"
          }
        ],
        "llm_analysis": "정보주체의 권리가 제6조(열람/정정)와 제4조(동의 철회)에 분산되어 있으나, 처리정지 청구권이 누락됨"
      },
      "recommendation": "정보주체의 권리를 하나의 조항으로 통합하고, 처리정지 청구권 추가 필요",
      "severity": "medium",
      "trigger_a2": true
    },
    {
      "std_article_id": "urn:std:provide:art:010",
      "std_article_title": "개인정보 보호책임자",
      "parent_id": "제10조",
      "is_truly_missing": true,
      "confidence": 0.98,
      "reason": "사용자 계약서에 해당 조항 완전 누락 (필수 조항)",
      "reverse_search_result": {
        "searched": true,
        "top_user_candidates": [],
        "llm_analysis": "계약서 전체에서 개인정보 보호책임자 지정 및 연락처에 관한 내용을 찾을 수 없음"
      },
      "recommendation": "개인정보 보호책임자 지정, 연락처, 업무 및 권한을 명시하는 조항 신규 작성 필요 (개인정보보호법 제31조)",
      "severity": "high",
      "trigger_a2": true
    }
  ],
  "missing_article_analysis": {
    "total_unmapped": 3,
    "truly_missing": 2,
    "distributed_in_user_contract": 1,
    "critical_missing": ["제8조", "제10조"]
  },
  "next_steps": {
    "trigger_a2_node": true,
    "trigger_a3_node": true,
    "a2_input": {
      "unmapped_std_articles": ["제8조", "제9조", "제10조"]
    },
    "a3_input": {
      "matched_pairs": [
        {"user": "제3조", "std": "제5조"},
        {"user": "제4조", "std": "제6조"}
      ]
    }
  }
}
```

---

## A2 Node: 체크리스트 검증 결과

### 목적
A1에서 매칭된 사용자 조항들이 표준 조항의 체크리스트 요구사항을 충족하는지 검증

### JSON 구조

```json
{
  "total_checklist_items": 25,
  "verified_items": 25,
  "passed_items": 18,
  "failed_items": 7,
  "user_article_results": [
    {
      "user_article_no": 3,
      "user_article_id": "user_article_003",
      "user_article_title": "개인정보의 수집",
      "matched_std_global_ids": [
        "urn:std:provide:art:005"
      ],
      "checklist_results": [
        {
          "check_text": "개인정보 수집 목적이 명시되어 있는가?",
          "reference": "urn:std:provide:art:005",
          "result": "YES",
          "evidence": "제3조 제1항에 '서비스 제공 및 계약 이행을 위해 개인정보를 수집한다'고 명시되어 있음"
        },
        {
          "check_text": "수집하는 개인정보 항목이 구체적으로 명시되어 있는가?",
          "reference": "urn:std:provide:art:005",
          "result": "YES",
          "evidence": "제3조 제2항에 '성명, 연락처, 이메일 주소'로 구체적으로 명시됨"
        },
        {
          "check_text": "최소 수집 원칙이 명시되어 있는가?",
          "reference": "urn:std:provide:art:005",
          "result": "YES",
          "evidence": "제3조 제1항에 '목적에 필요한 최소한의 개인정보를 수집'이라고 명시됨"
        },
        {
          "check_text": "동의 거부 시 서비스 제공 거부 금지 조항이 있는가?",
          "reference": "urn:std:provide:art:005",
          "result": "NO",
          "evidence": null
        }
      ]
    },
    {
      "user_article_no": 4,
      "user_article_id": "user_article_004",
      "user_article_title": "개인정보의 이용",
      "matched_std_global_ids": [
        "urn:std:provide:art:006"
      ],
      "checklist_results": [
        {
          "check_text": "개인정보 이용 목적이 명시되어 있는가?",
          "reference": "urn:std:provide:art:006",
          "result": "YES",
          "evidence": "제4조 제1항에 '명시한 목적 범위 내에서만 이용한다'고 명시됨"
        },
        {
          "check_text": "목적 외 이용 시 동의 절차가 명시되어 있는가?",
          "reference": "urn:std:provide:art:006",
          "result": "YES",
          "evidence": "제4조 제2항에 '목적 외 이용이 필요한 경우 정보주체의 동의를 받아야 한다'고 명시됨"
        }
      ]
    },
    {
      "user_article_no": 0,
      "user_article_id": "preamble",
      "user_article_title": "서문",
      "matched_std_global_ids": [
        "urn:std:provide:art:001"
      ],
      "checklist_results": [
        {
          "check_text": "계약 당사자가 명시되어 있는가?",
          "reference": "서문 + urn:std:provide:art:001",
          "result": "YES",
          "evidence": "서문에 '갑(데이터 제공자)과 을(데이터 이용자) 간의 계약'으로 명시됨"
        },
        {
          "check_text": "계약 목적이 명시되어 있는가?",
          "reference": "서문 + urn:std:provide:art:001",
          "result": "YES",
          "evidence": "제1조에 '데이터 제공 및 이용에 관한 사항을 정함'으로 명시됨"
        }
      ]
    }
  ],
  "processing_time": 12.5,
  "verification_date": "2024-11-04T10:35:00Z"
}
```

---

## A3 Node: 내용 상세 비교 결과

### 목적
A1에서 매칭된 조항들의 내용을 LLM으로 상세 비교하여 누락/불충분 항목 식별

### JSON 구조

```json
{
  "contract_id": "user_contract_20241104_001",
  "contract_type": "provide_std_contract",
  "total_articles": 15,
  "analyzed_articles": 12,
  "special_articles": 0,
  "processing_time": 45.2,
  "analysis_timestamp": "2024-11-04T10:40:00Z",
  "article_analysis": [
    {
      "user_article_no": 3,
      "user_article_title": "개인정보의 수집",
      "matched": true,
      "similarity": 0.87,
      "std_article_id": "제5조",
      "std_article_title": "개인정보의 수집 및 이용",
      "is_special": false,
      "reasoning": "표준계약서 제5조와 매칭됨",
      "matched_articles": [
        {
          "parent_id": "제5조",
          "global_id": "urn:std:provide:art:005",
          "title": "개인정보의 수집 및 이용",
          "score": 0.87,
          "num_sub_items": 3,
          "matched_sub_items": [1, 2, 3]
        }
      ],
      "suggestions": [
        {
          "selected_standard_articles": ["제5조"],
          "issue_type": "content",
          "missing_items": [
            "동의 거부 시 서비스 제공 거부 금지 조항"
          ],
          "insufficient_items": [
            "수집 목적 명시가 불충분함"
          ],
          "analysis": "사용자 계약서 제3조는 개인정보 수집의 기본 원칙을 다루고 있으나, 표준계약서 제5조에 비해 다음 항목이 누락되거나 불충분합니다:\n\n**누락 항목:**\n1. 동의 거부권 보장: 표준계약서는 '필요 최소한의 정보 외의 개인정보 수집에 동의하지 아니한다는 이유로 서비스 제공을 거부하여서는 아니 된다'는 조항이 있으나, 사용자 계약서에는 이 내용이 없습니다.\n\n**불충분 항목:**\n1. 수집 목적: 사용자 계약서는 '목적에 필요한 최소한'이라고만 명시하고 구체적인 수집 목적(서비스 제공, 계약 이행, 법적 의무 준수 등)을 명시하지 않았습니다.\n\n**권장사항:**\n- 제3조에 구체적인 수집 목적을 명시하는 항 추가\n- 동의 거부권 보장 조항 추가 (개인정보보호법 제16조 제2항)",
          "severity": "medium"
        }
      ],
      "analysis_timestamp": "2024-11-04T10:40:15Z"
    },

    {
      "user_article_no": 4,
      "user_article_title": "개인정보의 이용",
      "matched": true,
      "similarity": 0.91,
      "std_article_id": "제6조",
      "std_article_title": "개인정보의 이용 및 목적",
      "is_special": false,
      "reasoning": "표준계약서 제6조와 매칭됨",
      "matched_articles": [
        {
          "parent_id": "제6조",
          "global_id": "urn:std:provide:art:006",
          "title": "개인정보의 이용 및 목적",
          "score": 0.91,
          "num_sub_items": 2,
          "matched_sub_items": [1, 2]
        }
      ],
      "suggestions": [
        {
          "selected_standard_articles": ["제6조"],
          "issue_type": "content",
          "missing_items": [],
          "insufficient_items": [],
          "analysis": "사용자 계약서 제4조는 표준계약서 제6조의 내용을 충실히 반영하고 있습니다.\n\n**충족 항목:**\n1. 목적 제한 원칙: '명시한 목적 범위 내에서만 이용'이 명확히 명시됨\n2. 목적 외 이용 시 동의: '정보주체의 동의를 받아야 한다'고 명시됨\n\n**긍정적 평가:**\n- 개인정보 이용의 핵심 원칙이 모두 포함되어 있음\n- 표준계약서와 높은 일치도를 보임\n- 법적 요구사항을 충족함\n\n표준계약서 대비 누락되거나 불충분한 항목이 없습니다.",
          "severity": "info"
        }
      ],
      "analysis_timestamp": "2024-11-04T10:40:30Z"
    }
  ]
}
```

---

## 전체 플로우 요약

### 데이터 흐름

```
A1 Node 출력
├─ article_mappings → A3 Node 입력 (matched_pairs)
└─ unmapped_std_articles → A2 Node 입력 (unmapped_articles)

A2 Node 출력
└─ checklist_results → Report Agent

A3 Node 출력
└─ detailed_comparisons → Report Agent

Report Agent
└─ 최종 통합 보고서 생성
```

### JSON 연계 예시

```json
{
  "workflow": {
    "a1_output": {
      "matched_pairs": [
        {"user": "제3조", "std": "제5조"},
        {"user": "제4조", "std": "제6조"}
      ],
      "unmapped_std_articles": ["제8조", "제9조", "제10조"]
    },
    "a2_input": {
      "articles_to_check": ["제8조", "제9조", "제10조"]
    },
    "a2_output": {
      "missing_articles": ["제10조"],
      "partial_articles": ["제8조", "제9조"]
    },
    "a3_input": {
      "pairs_to_compare": [
        {"user": "제3조", "std": "제5조"},
        {"user": "제4조", "std": "제6조"}
      ]
    },
    "a3_output": {
      "compliant_pairs": [{"user": "제4조", "std": "제6조"}],
      "needs_improvement_pairs": [{"user": "제3조", "std": "제5조"}]
    }
  }
}
```

---

## 핵심 특징

1. **A1 → A2/A3 분기**: A1의 매칭 결과에 따라 A2와 A3가 병렬 실행
2. **상세한 신뢰도 점수**: 각 단계마다 confidence score 제공
3. **구체적인 권장사항**: 단순 문제 지적이 아닌 개선 방안 제시
4. **법적 근거 명시**: 개인정보보호법 조항 참조
5. **우선순위 분류**: 심각도(high/medium/low)에 따른 조치 우선순위
