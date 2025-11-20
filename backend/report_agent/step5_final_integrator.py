"""
Step5FinalIntegrator

체크리스트 결과를 통합하고 최종 보고서를 생성합니다.
"""

import logging
import json
import os
from datetime import datetime
from typing import Dict, List, Any
from openai import AzureOpenAI

logger = logging.getLogger(__name__)


class Step5FinalIntegrator:
    """
    Step 5: 최종 통합 보고서 생성
    
    - A2 체크리스트 결과 통합
    - 최종 보고서 포맷팅
    - 메타데이터 추가
    """
    
    def __init__(self):
        """
        Step5FinalIntegrator 초기화
        """
        self.client = None
        try:
            self.client = AzureOpenAI(
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version="2024-08-01-preview",
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
            )
            logger.info("Azure OpenAI 클라이언트 초기화 성공")
        except Exception as e:
            logger.warning(f"Azure OpenAI 클라이언트 초기화 실패: {e}. 서술형 보고서 생성 불가")
    
    def integrate(self, step4_result: Dict[str, Any], 
                 a2_result: Dict[str, Any],
                 a2_recovered_result: Dict[str, Any] = None,
                 user_contract_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        체크리스트 결과를 통합하여 최종 보고서 생성 (Primary + Recovered 병합)
        
        Args:
            step4_result: Step 4 결과 (포맷팅된 보고서)
            a2_result: A2 Primary 체크리스트 검증 결과 (None 가능)
            a2_recovered_result: A2 Recovered 체크리스트 검증 결과 (None 가능)
            user_contract_data: 사용자 계약서 원본 데이터 (조 내용 추출용)
            
        Returns:
            최종 통합 보고서 JSON
        """
        import time
        
        logger.info("📊 Step 5 최종 통합 시작")
        step5_start_time = time.time()
        
        # 사용자 계약서 데이터 저장 (종합분석 생성 시 사용)
        self.user_contract_data = user_contract_data
        
        # Step4 결과 복사
        final_report = step4_result.copy()
        
        # A2 Primary 결과 확인
        substep_start = time.time()
        if not a2_result:
            logger.warning("A2 Primary 체크리스트 결과가 없습니다. 체크리스트 통합 스킵")
            final_report["checklist_summary"] = {
                "total_items": 0,
                "passed_items": 0,
                "failed_items": 0,
                "unclear_items": 0,
                "manual_check_items": 0,
                "pass_rate": 0.0
            }
        else:
            # A2 Primary + Recovered 병합
            merged_a2_result = self._merge_a2_results(a2_result, a2_recovered_result)
            
            # 체크리스트 결과 통합
            final_report["user_articles"] = self._integrate_checklist_results(
                step4_result.get("user_articles", []),
                merged_a2_result
            )
            
            # 체크리스트 통계 추가
            final_report["checklist_summary"] = self._calculate_checklist_summary(merged_a2_result)
            
            primary_count = len(a2_result.get('matched_articles', [])) or len(a2_result.get('std_article_results', []))
            recovered_count = len(a2_recovered_result.get('std_article_results', [])) if a2_recovered_result else 0
            logger.info(f"  ✅ 체크리스트 통합 완료: Primary {primary_count}개 + Recovered {recovered_count}개 조항")
        logger.info(f"  ⏱️ 체크리스트 통합 완료 ({time.time() - substep_start:.1f}초)")
        
        # 조항별 서술형 보고서 생성
        substep_start = time.time()
        if self.client:
            final_report["user_articles"] = self._generate_narrative_reports(
                final_report.get("user_articles", []),
                final_report.get("contract_type", "unknown")
            )
        else:
            logger.warning("Azure OpenAI 클라이언트 없음. 서술형 보고서 생성 스킵")
        logger.info(f"  ⏱️ 서술형 보고서 생성 완료 ({time.time() - substep_start:.1f}초)")
        
        # 최종 생성 시간 업데이트
        final_report["final_generated_at"] = datetime.now().isoformat()
        
        step5_elapsed = time.time() - step5_start_time
        logger.info(f"✅ Step 5 최종 통합 완료 ({step5_elapsed:.1f}초)")
        
        return final_report
    
    def _merge_a2_results(self, a2_primary: Dict[str, Any], 
                         a2_recovered: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        A2 Primary와 A2 Recovered 결과 병합
        
        Recovered 결과는 A1 재검증 후의 매칭 결과를 기반으로 하므로,
        Primary에 없는 체크리스트 항목을 추가합니다.
        
        Args:
            a2_primary: A2 Primary 결과
            a2_recovered: A2 Recovered 결과 (None 가능)
            
        Returns:
            병합된 A2 결과
        """
        if not a2_recovered:
            logger.info("A2 Recovered 결과 없음. Primary만 사용")
            return a2_primary
        
        logger.info("A2 Primary + Recovered 병합 시작")
        
        # Primary 결과 복사
        merged = a2_primary.copy()
        
        # std_article_results 형식인 경우
        if 'std_article_results' in a2_primary and 'std_article_results' in a2_recovered:
            primary_results = merged['std_article_results']
            recovered_results = a2_recovered['std_article_results']
            
            # Recovered의 표준 조항들을 Primary에 추가
            primary_std_ids = {r['std_article_id'] for r in primary_results}
            
            added_count = 0
            for recovered_std in recovered_results:
                std_id = recovered_std['std_article_id']
                
                if std_id not in primary_std_ids:
                    # Primary에 없는 표준 조항 추가
                    primary_results.append(recovered_std)
                    added_count += 1
                    logger.info(f"  A2 Recovered 추가: {std_id} → 사용자 조항 {recovered_std.get('matched_user_articles')}")
            
            logger.info(f"A2 병합 완료: {added_count}개 표준 조항 추가")
        
        return merged
    
    def _integrate_checklist_results(self, user_articles: List[Dict], 
                                    a2_result: Dict[str, Any]) -> List[Dict]:
        """
        사용자 조항별로 체크리스트 결과 통합 및 필드명 정리
        
        Args:
            user_articles: Step4의 user_articles
            a2_result: A2 체크리스트 결과 (표준 조항 기준)
            
        Returns:
            체크리스트가 통합되고 필드명이 정리된 user_articles
        """
        # A2 결과를 사용자 조항 번호로 매핑
        a2_by_article = {}
        
        # A2 결과가 표준 조항 기준인 경우 (std_article_results)
        std_article_results = a2_result.get("std_article_results", [])
        if std_article_results:
            logger.info(f"A2 결과를 표준 조항 기준에서 사용자 조항 기준으로 변환 중...")
            
            # 표준 조항별로 순회
            for std_result in std_article_results:
                matched_users = std_result.get("matched_user_articles", [])
                checklist_results = std_result.get("checklist_results", [])
                
                # 체크리스트 항목별로 source_article_no 추출 및 매핑
                for checklist_item in checklist_results:
                    # source_article_no 추출 (방안 3)
                    source_article_no = self._extract_source_article_no(
                        checklist_item, 
                        matched_users
                    )
                    
                    if source_article_no is not None:
                        if source_article_no not in a2_by_article:
                            a2_by_article[source_article_no] = []
                        
                        # source_article_no 추가
                        checklist_with_source = checklist_item.copy()
                        checklist_with_source["source_article_no"] = source_article_no
                        a2_by_article[source_article_no].append(checklist_with_source)
            
            logger.info(f"변환 완료: {len(a2_by_article)}개 사용자 조항에 체크리스트 매핑됨")
        
        # 구 형식 (matched_articles) 지원 (하위 호환성)
        else:
            for matched_article in a2_result.get("matched_articles", []):
                user_article_no = matched_article.get("user_article_no")
                if user_article_no is not None:
                    a2_by_article[user_article_no] = matched_article.get("checklist_items", [])
        
        # 각 사용자 조항에 체크리스트 결과 추가 및 필드명 정리
        for article in user_articles:
            user_article_no = article.get("user_article_no")
            
            # 해당 조항의 체크리스트 결과 찾기
            checklist_items = a2_by_article.get(user_article_no, [])
            
            # 필드명 정리 (서술형 보고서 생성을 위해)
            # matched → matched_standard_articles
            article["matched_standard_articles"] = article.pop("matched", [])
            
            # insufficient → insufficient_items
            article["insufficient_items"] = article.pop("insufficient", [])
            
            # missing → missing_items  
            article["missing_items"] = article.pop("missing", [])
            
            # 체크리스트 결과 추가
            article["checklist_results"] = checklist_items
            
            # A3 fidelity_level 추가 (이미 있으면 유지)
            if "fidelity_level" not in article:
                article["fidelity_level"] = "unknown"
            
            logger.debug(f"사용자 조항 {user_article_no}: "
                        f"매칭 {len(article['matched_standard_articles'])}개, "
                        f"불충분 {len(article['insufficient_items'])}개, "
                        f"누락 {len(article['missing_items'])}개, "
                        f"체크리스트 {len(checklist_items)}개, "
                        f"fidelity_level: {article.get('fidelity_level', 'unknown')}")
        
        return user_articles
    
    def _extract_source_article_no(self, checklist_item: Dict[str, Any], 
                                   matched_users: List[Dict]) -> int:
        """
        체크리스트 항목의 evidence 또는 recommendation에서 조항 번호 추출
        
        Args:
            checklist_item: 체크리스트 항목
            matched_users: 매칭된 사용자 조항 리스트
            
        Returns:
            조항 번호 (정수) 또는 None
        """
        import re
        
        # 1. evidence에서 조항 번호 추출 시도 (YES 결과)
        evidence = checklist_item.get("evidence", "")
        if evidence:
            match = re.search(r'제(\d+)조', evidence)
            if match:
                article_num = int(match.group(1))
                for user_info in matched_users:
                    if user_info.get("user_article_no") == article_num:
                        return article_num
            
            if "서문" in evidence:
                for user_info in matched_users:
                    if user_info.get("user_article_no") == 0:
                        return 0
        
        # 2. recommendation에서 조항 번호 추출 시도 (NO 결과)
        recommendation = checklist_item.get("recommendation", "")
        if recommendation:
            match = re.search(r'제(\d+)조', recommendation)
            if match:
                article_num = int(match.group(1))
                for user_info in matched_users:
                    if user_info.get("user_article_no") == article_num:
                        return article_num
            
            if "서문" in recommendation:
                for user_info in matched_users:
                    if user_info.get("user_article_no") == 0:
                        return 0
        
        # 3. missing_explanation에서 조항 번호 추출 시도 (NO 결과)
        missing_explanation = checklist_item.get("missing_explanation", "")
        if missing_explanation:
            match = re.search(r'제(\d+)조', missing_explanation)
            if match:
                article_num = int(match.group(1))
                for user_info in matched_users:
                    if user_info.get("user_article_no") == article_num:
                        return article_num
        
        # 4. manual_check_reason에서 조항 번호 추출 시도 (MANUAL_CHECK_REQUIRED 결과)
        manual_check_reason = checklist_item.get("manual_check_reason", "")
        if manual_check_reason:
            match = re.search(r'제(\d+)조', manual_check_reason)
            if match:
                article_num = int(match.group(1))
                for user_info in matched_users:
                    if user_info.get("user_article_no") == article_num:
                        return article_num
            
            if "서문" in manual_check_reason:
                for user_info in matched_users:
                    if user_info.get("user_article_no") == 0:
                        return 0
        
        # 5. 패턴을 찾지 못하면 첫 번째 매칭 조항 사용 (폴백)
        if matched_users:
            logger.warning(f"조항 번호 추출 실패, 첫 번째 매칭 조항 사용: {evidence[:50] if evidence else recommendation[:50]}...")
            return matched_users[0].get("user_article_no")
        
        return None
    
    def _calculate_checklist_summary(self, a2_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        체크리스트 전체 통계 계산
        
        Args:
            a2_result: A2 체크리스트 결과
            
        Returns:
            체크리스트 통계
        """
        statistics = a2_result.get("statistics", {})
        
        return {
            "total_items": statistics.get("total_items", 0),
            "passed_items": statistics.get("passed_items", 0),
            "failed_items": statistics.get("failed_items", 0),
            "unclear_items": statistics.get("unclear_items", 0),
            "manual_check_items": statistics.get("manual_check_items", 0),
            "pass_rate": statistics.get("pass_rate", 0.0)
        }
    
    def _generate_narrative_reports(self, user_articles: List[Dict], 
                                    contract_type: str) -> List[Dict]:
        """
        각 조항별로 서술형 보고서 생성 (병렬 처리)
        
        Args:
            user_articles: 사용자 조항 리스트
            contract_type: 계약 유형
            
        Returns:
            서술형 보고서가 추가된 user_articles
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from openai import RateLimitError
        import time
        
        # 병렬 처리 함수
        def process_single_article(article_index, article):
            """단일 조항 처리 (재시도 로직 포함)"""
            max_retries = 3
            article_title = article.get('user_article_title', f'조항 {article_index}')
            
            for attempt in range(max_retries):
                try:
                    narrative = self._generate_single_article_narrative(article, contract_type)
                    article["narrative_report"] = narrative
                    logger.info(f"✅ [{article_index + 1}/{len(user_articles)}] '{article_title}' 서술형 보고서 생성 완료")
                    return article
                    
                except RateLimitError as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5  # 5초, 10초, 15초
                        logger.warning(f"⚠️ Rate Limit 도달: '{article_title}'. {wait_time}초 대기 후 재시도... (시도 {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"❌ '{article_title}' Rate Limit 초과로 폴백 보고서 생성")
                        article["narrative_report"] = self._generate_fallback_narrative(article)
                        return article
                        
                except Exception as e:
                    logger.error(f"❌ '{article_title}' 서술형 보고서 생성 실패: {e}")
                    article["narrative_report"] = self._generate_fallback_narrative(article)
                    return article
        
        # 병렬 실행 (최대 8개 동시)
        logger.info(f"🚀 서술형 보고서 병렬 생성 시작: {len(user_articles)}개 조항 (max_workers=8)")
        start_time = time.time()
        
        # 조항 인덱스와 함께 처리 (순서 추적용)
        article_with_index = list(enumerate(user_articles))
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            # 모든 조항을 병렬로 제출
            future_to_article = {
                executor.submit(process_single_article, idx, article): (idx, article)
                for idx, article in article_with_index
            }
            
            # 완료된 순서대로 결과 수집
            completed_count = 0
            for future in as_completed(future_to_article):
                completed_count += 1
                idx, article = future_to_article[future]
                
                # 진행률 로그
                if completed_count % 5 == 0 or completed_count == len(user_articles):
                    elapsed = time.time() - start_time
                    logger.info(f"📊 진행률: {completed_count}/{len(user_articles)} ({completed_count/len(user_articles)*100:.0f}%) - 경과 시간: {elapsed:.1f}초")
        
        elapsed_time = time.time() - start_time
        logger.info(f"✨ 서술형 보고서 병렬 생성 완료: {len(user_articles)}개 조항, 총 소요 시간: {elapsed_time:.1f}초")
        
        return user_articles
    
    def _generate_single_article_narrative(self, article_data: Dict[str, Any], 
                                          contract_type: str) -> str:
        """
        단일 조항에 대한 서술형 보고서 생성 (LLM 활용)
        
        Args:
            article_data: 조항 데이터
            contract_type: 계약 유형
            
        Returns:
            서술형 보고서 텍스트
        """
        # 클라이언트가 없으면 폴백 사용
        if not self.client:
            logger.warning("Azure OpenAI 클라이언트 없음. 폴백 보고서 생성")
            return self._generate_fallback_narrative(article_data)
        
        # 입력 데이터 준비 (Step5에서 정리된 필드명 사용)
        user_article_no = article_data.get('user_article_no')
        user_article_title = article_data.get('user_article_title', 'N/A')
        matched_standards = article_data.get('matched_standard_articles', [])
        insufficient_items = article_data.get('insufficient_items', [])
        missing_items = article_data.get('missing_items', [])
        checklist_results = article_data.get('checklist_results', [])
        
        # 서문(제0조) 특별 처리
        is_preamble = (user_article_no == 0)
        
        # 서문인 경우 누락/불충분 항목 모두 제거 (overall_missing으로 이동됨)
        if is_preamble:
            if missing_items:
                logger.warning(f"서문에 누락 항목이 남아있음 (제거): missing={len(missing_items)}")
                missing_items = []
            if insufficient_items:
                logger.warning(f"서문에 불충분 항목이 남아있음 (제거): insufficient={len(insufficient_items)}")
                insufficient_items = []
        
        # 사용자 조 내용 추출
        user_article_content = self._get_user_article_content(user_article_no)
        
        # 서문용 프롬프트 (긍정적 평가 + 불충분 항목)
        if is_preamble:
            prompt = f"""당신은 데이터 계약서 검증 전문가입니다. 아래는 계약서의 서문(제0조)에 대한 검증 데이터입니다.

## 검증 대상 조항
{user_article_title}

## 사용자 조항 원문
{user_article_content}

## 매칭된 표준 조항
{json.dumps(matched_standards, ensure_ascii=False, indent=2)}

## 체크리스트 검증 결과
{json.dumps(checklist_results, ensure_ascii=False, indent=2)}

서문은 계약의 서두에 위치하여 당사자 정보를 정리하고 계약의 기본 목적과 방향성을 소개하는 역할을 합니다. 
아래 기준에 따라 서문에 대한 서술형 검토 보고서를 작성하세요.

🔵 1. 보고서 구성
 조항 소개  
- 서문이 계약 구조에서 어떤 기능을 하는지 간단히 설명  
- 해당 서문의 전체적인 인상 및 평가 개괄  

② 긍정적으로 평가되는 요소  
- 당사자 명칭, 법적 형태, 대표자, 주소 등 기본 정보가 정확히 표현된 부분  
- 계약 목적이 명확하게 서술된 경우 자연스럽게 언급  
- 잘 작성된 문구는 요약하여 서술
- 체크리스트에서 통과한 항목(result: YES)이 있다면 자연스럽게 언급

③ 종합적 판단  
- “기본 구조는 양호하나 일부 내용은 추가적인 보완이 필요하다” 등 자연스러운 결론  
- 필요한 개선 방향을 간결히 제시  

🔵 2. 가독성 최적화 규칙

- 각 문단은 하나의 주제만 다루고 3~5문장 이내로 유지한다.  
- 동일하거나 유사한 의미는 반복하지 않는다.  
- 핵심 내용만 선별하여 압축적으로 표현하되 서술형 자연스러움을 유지한다.  
- 서문 특성상 정의·권리·의무 등 본문에서 다뤄야 할 내용이 부족한 것은 문제로 삼지 말고, 
  “이후 조항에서 명확히 규정될 필요가 있다”는 식으로 부드럽게 처리한다.  
- 불충분 요소는 반드시 포함하되 과도하게 길거나 기술적 설명은 피한다.  

🔵 3. 금지 규칙

- “표준계약서”, “매칭됨”, “글로벌ID”, “subclause” 등 기술적·메타적 용어 금지  
- JSON 구조 설명 금지  
- 원문 전체 복사 금지 (필요 시 요약만)  
- AI/LLM 분석 언급 금지  

🔵 4. 출력 형식

- “서문에 대한 검토 보고서”라는 제목으로 시작  
- 표·목록 최소화, 자연스러운 단락 중심  
- 법무팀이 작성한 정식 보고서 문체  
- 차분하고 객관적이며 논리적이고 지나치게 장황하지 않은 문장  """

        else:
            # 일반 조항용 프롬프트 (서술형 보고서)
            prompt = f"""당신은 데이터 계약서 검증 전문가입니다. 아래 검증 데이터를 바탕으로 서술형 보고서를 생성하세요.
## 입력 데이터
### 검증 대상 조항
{user_article_title}

### 사용자 조항 원문
{user_article_content}
※ 사용자 조항 원문은 의미 파악을 위한 참고 용도로만 사용하며, 문장을 그대로 복붙하지 않는다. 필요한 경우 1~2문장 정도로 간단히 요약하여 언급한다.

### 매칭된 표준 조항
{json.dumps(matched_standards, ensure_ascii=False, indent=2)}

### 불충분한 조항
{json.dumps(insufficient_items, ensure_ascii=False, indent=2)}

### 누락된 조항
{json.dumps(missing_items, ensure_ascii=False, indent=2)}

### 체크리스트 검증 결과
{json.dumps(checklist_results, ensure_ascii=False, indent=2)}

---

당신은 데이터 거래 계약서 검증 전문 컨설턴트입니다.
입력으로 제공되는 분석 결과(예: 불충분 항목, 누락 항목, 체크리스트 결과 등)를 바탕으로,
사용자 계약서가 데이터 거래 계약에서 요구되는 기준을 얼마나 충족하는지 검토하고
그 결과를 서술형 보고서로 작성하십시오.

보고서는 다음 목적을 갖습니다:
- 충족된 기준 파악
- 불충분하거나 모호한 요소 파악
- 누락된 핵심 요소 파악
- 실무적 리스크 제시
- 어떤 조 단위 보완이 필요한지 안내

문체는 법무팀 또는 외부 컨설턴트가 작성한 “정식 검토 보고서” 스타일을 따른다.


📘 보고서 작성 원칙

1) 표현 규칙
- “매칭됨”, “유사도”, “벡터”, “스코어”, “글로벌ID” 등 기술적 용어 사용 금지
- “AI 분석”, “LLM 판단”, “모델이 보기엔” 등 모델 기반 표현 금지
- JSON, ID, 내부 구조 언급 금지
- 사용자 계약서 원문은 그대로 복사·붙여넣기 금지 (1~2문장 요약만 허용)

📌 표준계약서 관련 표현 규칙
- 본문(1~5, 7번 섹션)에서는 “표준계약서”라는 단어 사용 금지
- 대신 “일반적으로 요구되는 데이터 제공 기준”,  
  “통상적으로 포함되는 품질 관리 사항” 등 자연어로 대체
- 단, “6. 개선 권고사항” 섹션에서는  
  “표준계약서 ○조 ○항을 참고할 수 있음” 정도의 자연스러운 언급만 허용


2) 가독성 규칙
- 한 단락에는 하나의 주제만 다룬다
- 모든 단락은 3~5문장으로 구성
- 보고서는 반드시 **7개의 섹션만** 사용한다 (제목 고정)
- 각 섹션은 1~3개 단락으로 작성
- 불충분/누락 항목이 많아도 나열형 문장 금지 → 주제별로 묶어 압축 서술
- 표현은 간결하고 밀도 있게 작성

⚠️ 중요한 규칙:  
보고서 상단에 **제목을 절대 생성하지 않는다**  
예: “검토 보고서: 제11조”, “결과 보고서”, “Analysis” 등 생성 금지  
→ **출력은 반드시 ‘1. 검토 개요’로 시작**해야 한다.


3) 긍정적 평가 작성 규칙
- 충족된 기준은 자연스럽게 설명
- std_clause_title의 의미를 자연어로 변환해 표현
  예: “데이터 반환 절차가 마련되어 있음”
  예: “정보보호 의무가 적절히 규정됨”
- 체크리스트 YES 결과는 긍정적 평가에 자연스럽게 통합
- 충족 사항이 많을 경우 구체적으로 기술


4) 불충분하거나 불명확한 요소 작성 규칙
- **insufficient_items가 비어 있으면 \"불충분한 요소가 없습니다\"라고만 작성**
- **insufficient_items가 있을 때만 구체적인 불충분 내용을 작성:**
  - 불충분 항목은 주제별로 묶어 요약 (데이터 범위 / 절차 / 책임 등)
  - 중복 없이 핵심만 요약
  - \"해석이 애매한 부분\", \"실무상 분쟁 가능성\" 등 표현 활용
  - 단정적/확정적 표현 금지 (\"반드시 문제가 된다\" 등 금지)
- **절대 금지: 사용자 조항 원문만 보고 임의로 불충분 사항을 만들어내는 행위**



5) 누락된 핵심 요소 작성 규칙
- **missing_items가 비어 있으면 \"누락된 내용이 없습니다\"라고만 작성**
- **missing_items가 있을 때만 구체적인 누락 내용을 작성:**
  - missing 항목 설명 시 \"조항 번호\" 언급 금지  
    → 반드시 \"개념 기반\" 자연어 설명 사용
    예: \"데이터 품질 보증 기준이 포함되지 않음\"
    예: \"종료 후 절차가 누락됨\"
  - 왜 해당 요소가 필요한지 실무 중심으로 설명
  - 과장된 위험 묘사 금지 (금전·법적 제재 구체 추정 금지)
- **절대 금지: 사용자 조항 원문만 보고 임의로 누락 사항을 만들어내는 행위**


6) AI가 판단할 수 없는 항목(MANUAL_CHECK_REQUIRED)
- 해당 항목은 반드시 보고서 본문에 포함
- “추가 확인이 필요함” 수준으로만 서술
- manual_check_reason을 자연어로 재구성
- 어떠한 결론도 단정하지 않음


7) 종합 판단
- 전체 충족도와 안정성에 대한 간단한 결론 제시
예:  
  - “기본 구조는 적절하나 일부 절차적 요소는 보완 필요함”  
  - “핵심 요소는 대부분 반영되어 있으나 실무적 위험이 일부 확인됨”  


8) 섹션 구조 및 제목 규칙 (매우 중요)
보고서는 아래 7개 섹션을 “이 순서대로, 정확한 제목으로” 출력해야 한다.

1. 검토 개요  
2. 충족된 기준  
3. 불충분한 요소  
4. 누락된 핵심 요소  
5. 실무적 리스크  
6. 개선 권고사항  
7. 종합 판단

- 제목 형식은 반드시 “숫자. 제목”
- 제목을 변경/통합/삭제 금지
- 추가 섹션 생성 금지
- 어떤 섹션이 거의 비어 있어도 반드시 생성  
  (예: “누락된 내용이 없습니다”)


**각 섹션별 필수 작성 규칙 (매우 중요):**
- **3. 불충분한 요소**: 
  - insufficient_items가 비어있으면 → "불충분한 요소가 없습니다"
  - insufficient_items가 있을 때만 구체적 내용 작성
  
- **4. 누락된 핵심 요소**: 
  - missing_items가 비어있으면 → "누락된 내용이 없습니다"
  - missing_items가 있을 때만 구체적 내용 작성
  
- **5. 실무적 리스크**: 
  - insufficient_items와 missing_items가 **모두 비어있으면** → "본 조항은 검증 기준을 충족하고 있어 특별한 실무적 리스크가 확인되지 않았습니다"
  - 하나라도 있으면 해당 항목의 analysis 내용 기반으로만 작성
  
- **6. 개선 권고사항**: 
  - insufficient_items와 missing_items가 **모두 비어있으면** → "현재 상태로 유지하되, 향후 계약 갱신 시 최신 기준을 참고할 것을 권장합니다"
  - 하나라도 있으면 해당 항목의 analysis 내용 기반으로만 작성
"""

        # 🔥 최종 출력 규칙 추가 (JSON 직접 출력)
        final_prompt = prompt + """

📌 출력 생성 절차 (필수)

1) 먼저, 내부적으로 고품질의 서술형 보고서를 완성한다.
   - 1~7번 섹션 규칙을 모두 적용하여 자연어 보고서를 작성한다.
   - 이 자연어 보고서는 출력하지 않는다.

2) 그런 다음, 내부적으로 생성한 보고서의 각 섹션 내용을 그대로 아래 JSON 구조의 값에 채워 넣는다.
   - 요약하거나 축소하지 않는다.
   - 자연어 단락은 그대로 여러 문장으로 유지한다.

3) 최종 출력은 반드시 다음 JSON 구조만 포함해야 한다.
   - JSON 바깥에 어떤 텍스트도 추가해서는 안 된다.
   - 코드블록(```json)도 사용하지 않는다.

⚠️ 중요: JSON 키는 반드시 아래의 영어 키를 정확히 사용해야 한다. 한글 키나 다른 형식은 절대 사용하지 말 것.

{
  "article_title": "{user_article_title}",
  "sections": {
    "section_1_overview": "...",
    "section_2_fulfilled_criteria": "...",
    "section_3_insufficient_elements": "...",
    "section_4_missing_core_elements": "...",
    "section_5_practical_risks": "...",
    "section_6_improvement_recommendations": "...",
    "section_7_comprehensive_judgment": "..."
  }
}

4) 각 섹션 값은 반드시 여러 문장으로 구성된 자연어 단락이어야 한다.
   - 단락 수와 문장 수를 임의로 줄이거나 요약하지 않는다.
   - 섹션 구조(1~7)는 반드시 유지해야 한다.

5) JSON 키 규칙 (매우 중요):
   - "section_1_overview" (O) / "1_검토개요" (X)
   - "section_2_fulfilled_criteria" (O) / "2_충족된기준" (X)
   - "section_3_insufficient_elements" (O) / "3_불충분한요소" (X)
   - "section_4_missing_core_elements" (O) / "4_누락된핵심요소" (X)
   - "section_5_practical_risks" (O) / "5_실무적리스크" (X)
   - "section_6_improvement_recommendations" (O) / "6_개선권고사항" (X)
   - "section_7_comprehensive_judgment" (O) / "7_종합판단" (X)
   
   반드시 영어 키만 사용하고, 한글 키는 절대 사용하지 말 것."""

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "당신은 데이터 계약서 검증 전문가입니다. 내부적으로 고품질의 서술형 보고서를 생성한 후, 반드시 JSON 형식으로만 출력하세요. JSON 바깥에 어떤 텍스트도 추가하지 마세요."},
                {"role": "user", "content": final_prompt}
            ],
            temperature=0.3,
            max_tokens=2500
        )
        
        result = response.choices[0].message.content.strip()
        
        # 🔥 LLM이 JSON을 직접 출력하므로 바로 반환 (파싱 불필요)
        logger.info(f"LLM JSON 보고서 생성 완료: {user_article_title} (토큰: {response.usage.total_tokens})")
        
        return result
    

    

    
    def _generate_fallback_narrative(self, article_data: Dict[str, Any]) -> str:
        """
        LLM 호출 실패 시 폴백 JSON 보고서 생성
        
        Args:
            article_data: 조항 데이터
            
        Returns:
            기본 JSON 형식의 보고서
        """
        user_article_title = article_data.get('user_article_title', 'N/A')
        matched_count = len(article_data.get('matched_standard_articles', []))
        insufficient_count = len(article_data.get('insufficient_items', []))
        missing_count = len(article_data.get('missing_items', []))
        checklist_results = article_data.get('checklist_results', [])
        
        passed_count = sum(1 for c in checklist_results if c.get('result') == 'YES')
        failed_count = sum(1 for c in checklist_results if c.get('result') == 'NO')
        
        # 폴백 JSON 구조 (영어 키 사용)
        fallback_json = {
            "article_title": user_article_title,
            "sections": {
                "section_1_overview": f"본 조항에 대한 검토를 수행했습니다. {matched_count}개의 표준 조항과 매칭되었으며, 체크리스트 {passed_count}개 항목을 충족하고 있습니다.",
                "section_2_fulfilled_criteria": f"체크리스트 {passed_count}개 항목이 충족되었습니다." if passed_count > 0 else "충족된 항목이 없습니다.",
                "section_3_insufficient_elements": f"{insufficient_count}개의 불충분한 항목이 확인되었습니다." if insufficient_count > 0 else "불충분한 요소가 없습니다.",
                "section_4_missing_core_elements": f"{missing_count}개의 누락된 항목이 확인되었습니다." if missing_count > 0 else "누락된 내용이 없습니다.",
                "section_5_practical_risks": f"{failed_count}개의 미충족 체크리스트가 확인되었습니다." if failed_count > 0 else "특별한 리스크가 없습니다.",
                "section_6_improvement_recommendations": "상세 내용은 구조화된 데이터를 참조하시기 바랍니다.",
                "section_7_comprehensive_judgment": "LLM 호출 실패로 인해 기본 폴백 보고서가 생성되었습니다. 상세 분석을 위해 재시도를 권장합니다."
            }
        }
        
        return json.dumps(fallback_json, ensure_ascii=False)


    def _get_user_article_content(self, user_article_no: int) -> str:
        """
        사용자 조항 원문 내용 추출
        
        Args:
            user_article_no: 사용자 조항 번호
            
        Returns:
            사용자 조항 원문 텍스트
        """
        if not self.user_contract_data:
            return "N/A (사용자 계약서 데이터 없음)"
        
        articles = self.user_contract_data.get('articles', [])
        
        for article in articles:
            if article.get('number') == user_article_no:
                title = article.get('title', '')
                content = article.get('content', '')
                
                # 조 전체 내용 구성
                full_content = f"제{user_article_no}조"
                if title:
                    full_content += f"({title})"
                full_content += f"\n{content}"
                
                return full_content
        
        return f"N/A (제{user_article_no}조 내용을 찾을 수 없음)"


# 출력 형식 명시 추가됨