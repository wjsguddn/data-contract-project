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
        logger.info("Step 5 최종 통합 시작")
        
        # 사용자 계약서 데이터 저장 (종합분석 생성 시 사용)
        self.user_contract_data = user_contract_data
        
        # Step4 결과 복사
        final_report = step4_result.copy()
        
        # A2 Primary 결과 확인
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
            logger.info(f"체크리스트 통합 완료: Primary {primary_count}개 + Recovered {recovered_count}개 조항")
        
        # 조항별 서술형 보고서 생성
        if self.client:
            logger.info("조항별 서술형 보고서 생성 시작")
            final_report["user_articles"] = self._generate_narrative_reports(
                final_report.get("user_articles", []),
                final_report.get("contract_type", "unknown")
            )
        else:
            logger.warning("Azure OpenAI 클라이언트 없음. 서술형 보고서 생성 스킵")
        
        # 최종 생성 시간 업데이트
        final_report["final_generated_at"] = datetime.now().isoformat()
        
        logger.info(f"Step 5 최종 통합 완료")
        
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
            
            logger.debug(f"사용자 조항 {user_article_no}: "
                        f"매칭 {len(article['matched_standard_articles'])}개, "
                        f"불충분 {len(article['insufficient_items'])}개, "
                        f"누락 {len(article['missing_items'])}개, "
                        f"체크리스트 {len(checklist_items)}개")
        
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
        
        # 병렬 실행 (최대 5개 동시)
        logger.info(f"🚀 서술형 보고서 병렬 생성 시작: {len(user_articles)}개 조항 (max_workers=5)")
        start_time = time.time()
        
        # 조항 인덱스와 함께 처리 (순서 추적용)
        article_with_index = list(enumerate(user_articles))
        
        with ThreadPoolExecutor(max_workers=5) as executor:
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

③ AI가 판단할 수 없는 항목 (있는 경우)
- 체크리스트 검증 결과에서 result가 "MANUAL_CHECK_REQUIRED"인 항목들이 있을 수 있다.
- 이는 계약서 원문만으로는 판단이 어려워 실제 계약 당사자나 법무팀의 추가 확인이 필요한 사항이다.
- 이러한 항목들도 반드시 종합분석에 포함하여 "추가 확인이 필요한 사항"으로 자연스럽게 서술한다.
- manual_check_reason에 명시된 이유를 바탕으로 왜 추가 확인이 필요한지 설명한다.  


 종합적 판단  
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
            # 일반 조항용 프롬프트 (기존 로직)
            prompt = f"""당신은 데이터 계약서 검증 전문가입니다. 아래 구조화된 검증 데이터를 바탕으로 사용자가 이해하기 쉬운 서술형 보고서를 작성해주세요.
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

# 📘 역할
당신은 데이터 계약서 검토 전문 컨설턴트입니다.  
위의 분석 데이터를 기반으로 **사용자가 직접 읽는 서술형 보고서**를 작성합니다.

보고서는 **기술적 표현 없이 자연스러운 법무팀 문체**,  
**조항의 역할과 실무적 의미 중심**으로 작성되어야 합니다.

---

# 📘 보고서 작성 원칙

## 1) 표현 규칙
- “매칭됨”, “유사도”, “글로벌ID” 등 기술적 표현 금지  
- “표준계약서”, “AI 분석”, “모델 판단” 같은 문구 금지  
- JSON 구조나 내부 식별자 표시 금지  
- 사용자 원문을 그대로 인용하거나 길게 반복 금지 (요약만 허용)

## 2) 가독성 규칙(중요)
- 한 단락에는 **하나의 주제만** 다룸  
- 단락 길이는 3~5문장 유지  
- 전체 보고서는 **3~6개 단락**으로 구성  
- 불충분/누락 항목이 많아도 단순 나열 금지  
  → 주제가 같은 요소끼리 묶어 자연스럽게 설명  
- 정보는 모두 포함하되 표현은 간결하고 밀도 있게 유지  
  (“내용 유지 + 표현 압축” 원칙)

## 3) 긍정적 평가 작성 규칙
- 매칭된 표준 조항은 “해당 요구사항을 충족했다”는 의미  
- std_clause_title을 활용해 **조항이 다루는 주제를 자연어로 풀어 씀**
  (예: “데이터 반환 절차가 마련되어 있으며”, “비밀유지 의무가 명확히 규정되어 있음” 등)
- 체크리스트 YES 항목도 자연스럽게 반영  
- 매칭 항목이 많을수록 긍정적 평가도 구체적으로 작성

## 4) 부족하거나 불명확한 요소 작성 규칙
- 불충분 항목을 기준으로 자연스럽게 묶어서 설명  
- 예: 데이터 품질·이용범위·접속정보 삭제·종료 후 의무 등  
- 동일 내용 반복 없이 핵심 의미만 간결하게 해석

## 5) 누락된 핵심 조치 설명 규칙
- missing 항목을 설명할 때 “조항 번호”를 말하지 말고  
  **그 조항이 다루는 핵심 개념을 자연스럽게 요약**  
- 왜 필요한지, 없으면 어떤 위험이 있는지 실무 관점에서 설명  
- 과장된 위험 설명 금지 (추측 금지, 일반적 위험만 서술)

## 6) AI가 판단할 수 없는 항목(MANUAL_CHECK_REQUIRED)
- 이 항목은 반드시 보고서에 포함  
- “확인이 필요하다”는 결론만 제시하고 예단 금지  
- manual_check_reason을 자연스럽게 의미만 재구성하여 설명

## 7) 종합적 판단
- 전체적인 인상을 요약  
- “기본 구조는 적절하나 ~이 부족함” 또는  
  “핵심 요소 대부분 반영되었으나 ~ 개선 필요” 등  
- 조항의 성격과 분석 데이터 기반으로 자연스럽게 결론 제시

## 8) 개선 권고사항
- 불충분·누락 요소에 대한 구체적 조언 제시  
- 단, 조문 문장을 직접 작성하지 말고  
  “~을 명확히 규정하는 것이 바람직합니다” 수준의 실무적 권고만 작성

---

# 📘 출력 형식

아래 형식으로 출력:


- 제목 한 줄  
- 이후 전체 보고서는 *순수 서술형 문단*으로 작성  
- 불릿포인트는 불가피한 경우에만 최소한으로 사용  

---

# 📘 매우 중요한 추가 규칙 (프롬프트 충돌 방지)

## 🔹 사용자 조항 원문은 “참고용”으로만 사용  
→ 원문 문장 구조를 재사용하거나 그대로 복붙하지 말 것

## 🔹 모든 부족/누락 항목을 반드시 포함  
→ 단, 주제별로 묶어 압축 서술

## 🔹 위험성 설명은 “일반적 실무 리스크” 수준만  
→ 법률적 제재·금전 추정 등 과장 금지

## 🔹 보고서는 반드시 ‘사람이 작성한 컨설팅 보고서 톤’으로 작성 """

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "당신은 데이터 계약서 검증 전문가입니다. 구조화된 데이터를 사용자 친화적인 서술형 보고서로 변환하는 것이 당신의 역할입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )
        
        result = response.choices[0].message.content.strip()
        logger.info(f"LLM 서술형 보고서 생성 완료: {user_article_title} (토큰: {response.usage.total_tokens})")
        
        return result
    
    def _generate_fallback_narrative(self, article_data: Dict[str, Any]) -> str:
        """
        LLM 호출 실패 시 폴백 서술형 보고서 생성
        
        Args:
            article_data: 조항 데이터
            
        Returns:
            기본 서술형 보고서
        """
        user_article_title = article_data.get('user_article_title', 'N/A')
        matched_count = len(article_data.get('matched', []))
        insufficient_count = len(article_data.get('insufficient', []))
        missing_count = len(article_data.get('missing', []))
        checklist_results = article_data.get('checklist_results', [])
        
        passed_count = sum(1 for c in checklist_results if c.get('result') == 'YES')
        failed_count = sum(1 for c in checklist_results if c.get('result') == 'NO')
        
        report = f"📄 {user_article_title} 검토 결과\n\n"
        
        if matched_count > 0:
            report += f"본 조항은 {matched_count}개의 표준 조항과 매칭되었습니다. "
        
        if passed_count > 0:
            report += f"체크리스트 {passed_count}개 항목을 충족하고 있습니다. "
        
        if insufficient_count > 0 or missing_count > 0 or failed_count > 0:
            report += f"\n\n다만, {insufficient_count}개의 불충분한 항목, {missing_count}개의 누락된 항목, {failed_count}개의 미충족 체크리스트가 확인되었습니다. "
            report += "상세 내용은 구조화된 데이터를 참조하시기 바랍니다."
        
        return report


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
