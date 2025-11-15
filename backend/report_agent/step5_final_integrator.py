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
        각 조항별로 서술형 보고서 생성
        
        Args:
            user_articles: 사용자 조항 리스트
            contract_type: 계약 유형
            
        Returns:
            서술형 보고서가 추가된 user_articles
        """
        for article in user_articles:
            try:
                narrative = self._generate_single_article_narrative(article, contract_type)
                article["narrative_report"] = narrative
                logger.info(f"조항 '{article.get('user_article_title')}' 서술형 보고서 생성 완료")
            except Exception as e:
                logger.error(f"조항 '{article.get('user_article_title')}' 서술형 보고서 생성 실패: {e}")
                article["narrative_report"] = self._generate_fallback_narrative(article)
        
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

## 검증 대상 조항
{user_article_title}

## 사용자 조항 원문
{user_article_content}
사용자 조항 원문은 필요한 경우 의미 파악을 위한 참고 용도로만 사용하며, 원문 전체를 직접 반복하거나 그대로 인용하지 않습니다. 필요한 경우 핵심 내용만 간단히 요약하여 언급합니다.

## 매칭된 표준 조항
{json.dumps(matched_standards, ensure_ascii=False, indent=2)}

## 불충분한 조항
{json.dumps(insufficient_items, ensure_ascii=False, indent=2)}

## 누락된 조항
{json.dumps(missing_items, ensure_ascii=False, indent=2)}

## 체크리스트 검증 결과
{json.dumps(checklist_results, ensure_ascii=False, indent=2)}

다음은 데이터 계약서 검증 에이전트가 추출한 분석 결과이다.
입력으로는 아래 항목들이 제공된다:

사용자 조항 원문

조항 분석 결과(불충분/누락/위험 요소 등)

체크리스트 평가 결과

표준계약서와의 매칭 여부 정보(LLM용 내부 데이터)

너의 역할은 이 분석 결과를 사용자가 읽는 ‘서술형 보고서’로 자연스럽게 재구성하는 것이다.

보고서는 반드시 아래 기준을 따른다:

1) 보고서 스타일 규칙

사용자에게 기술적 용어(매칭됨, 글로벌ID, 표준 제○조) 등을 직접 언급하지 않는다.

“LLM이 분석한 결과” 또는 “AI가 판단한 내용”이라는 표현은 금지한다.

사람이 직접 읽고 작성한 정식 보고서처럼 자연스럽고 매끄럽게 작성한다.

잘 작성된 부분, 부족한 부분, 누락된 부분, 보완이 필요한 이유, 구체적 개선 권고를 중심으로 서술한다.

일반적인 데이터 제공·이용 계약에서 요구되는 내용에 비추어 논리적으로 평가하는 방식으로 작성한다.

문단 단위의 서술형 보고서여야 한다.
(표, 목록은 필요할 때만 최소한으로 사용)

2) 보고서 구성 규칙

보고서는 다음 순서로 작성한다:

① 조항에 대한 전체 평가 소개

해당 조항이 어떤 역할을 하는 조항인지 정말 간단히 설명

전반적인 인상 또는 평가 개괄

② 긍정적으로 평가되는 요소

사용자 조항 중 실제로 잘 작성된 부분을 자연스럽게 서술

반환·폐기 절차 / 비밀유지 / 책임 등 잘 반영된 부분을 간단히 칭찬하는 톤으로 작성

③ 부족하거나 불명확한 요소

파생데이터 처리 기준 부족

접속정보·토큰 삭제 의무의 부재

제3자 제공분 처리 규정 누락

비밀유지 기간 미명시

종료 후 지속되어야 하는 책임 범위의 부족
→ 입력 데이터에 있는 항목을 기반으로 자연스럽게 서술

④ 누락된 핵심 조치

분석 결과에서 "missing" 상태인 항목을 논리적으로 설명

왜 필요한지, 어떤 위험이 있는지 함께 서술

⑤ AI가 판단할 수 없는 항목 (MANUAL_CHECK_REQUIRED)

체크리스트 검증 결과에서 result가 "MANUAL_CHECK_REQUIRED"인 항목들이 있을 수 있다.

이는 계약서 원문만으로는 판단이 어려워 실제 계약 당사자나 법무팀의 추가 확인이 필요한 사항이다.

이러한 항목들도 반드시 종합분석에 포함하여 "추가 확인이 필요한 사항"으로 자연스럽게 서술한다.

manual_check_reason에 명시된 이유를 바탕으로 왜 추가 확인이 필요한지 설명한다.

⑤ 종합적 판단

“기본 구조는 잘 되어 있으나 핵심 안전장치가 일부 빠져 있다”
또는 입력 데이터를 기반으로 한 자연스러운 결론

⑥ 개선 권고사항

부족/누락 항목에 대해 실제로 넣어야 할 내용들을 제안

조항 문장을 직접 쓰지 말고, “~을 명확히 규정할 필요가 있다” 수준으로 작성할 것

🔵 3) 금지 규칙

“제○조와 매칭됩니다” 같은 기술적 문장 금지

“표준계약서”라는 단어를 직접 사용하지 말 것

글로벌 ID, 항목 번호 등 내부 식별자를 출력하지 말 것

분석 데이터의 JSON 구조를 직접 노출하지 말 것

AI나 모델이 판단했다는 문구 금지

입력 데이터의 전문(원문)을 그대로 복붙하는 것 금지
(필요하면 요약하여 언급)

🔵 4) 출력 톤

법무팀 또는 외부 컨설턴트가 작성한 “정식 검토 보고서”의 문체

차분하고 객관적이며 논리적인 문장

판단 근거는 조항의 일반적 요구사항 기반으로 자연스럽게 기술

과도하게 기술적이거나 기계적인 문장 금지

🔵 5) 출력 형식

제목 포함한 서술형 보고서

불릿포인트는 최소한으로만 사용

전체 텍스트는 자연스럽고 매끄러운 연결로 구성

사용자에게 직접 수행해야 할 조치가 무엇인지 인지할 수 있게 작성

🔵 6) 가독성 최적화 규칙 (중요)

- 불충분/누락 항목이 많더라도 내용을 그대로 나열하지 말고, 성격이 비슷한 항목끼리 자연스럽게 묶어 단락 단위로 서술한다.
(예: 데이터 품질 관련 부족사항을 하나의 단락으로 묶는 방식)

- 동일하거나 유사한 의미의 내용을 반복하지 않고, 핵심 내용만 선별하여 간결하게 표현한다.

- 각 문단은 3~5문장 이내로 유지하여 과도한 정보 밀집을 피하고, 자연스럽게 읽히는 길이로 조정한다.

- 필요 이상의 장황한 설명이나 예시를 피하고, 핵심 의미만 남기되 서술형 문체는 유지한다.

- 전체 보고서는 필수 내용을 포함하되, 전체 길이가 지나치게 길어지지 않도록 정보를 압축하여 전달한다.
(‘핵심 정보 유지 + 표현 최적화’가 원칙)

- 불충분·누락 요소는 반드시 포함하되, 장문의 세부 설명 대신 논리적 요약을 우선한다.
(예: “데이터 품질 보증 기준이 구체적으로 규정되어 있지 않아 분쟁의 가능성이 있다” 수준으로 표현)

- 길이를 인위적으로 줄이려고 누락된 요소를 삭제해서는 안 되며, “내용은 유지하되 밀도는 낮추는 방식”으로 정리한다.

- 한 문단에 1개의 주제만 다루고, 새로운 주제는 반드시 새 단락을 생성한다.

🔵 OUTPUT FORMAT

“제8조(계약 종료 후 후속 조치)에 대한 검토 보고서”
(입력으로 들어오는 조항명이 자동으로 들어가도록)

그 후 서술형 보고서를 작성한다.
작성시 중요사항 
- 입력된 불충분·누락·위험 요소를 하나도 빠짐없이 포함한다.
- 입력되지 않은 새로운 판단, 원인, 리스크, 주장 등을 임의로 추가하지 않는다.
- 분석 결과는 재구성하되 입력된 의미를 벗어나지 않는다.
- 보고서는 사용자용 서술형 문체로 작성하며 과도한 법률 문체를 사용하지 않는다.
- 소제목, 표, 목록은 사용하지 않으며 자연스러운 단락 중심으로 작성한다.
- 동일한 스타일과 톤을 모든 조항에 대해 일관되게 유지한다.
- 부족하거나 누락된 내용이 많더라도 한 문단에 과도하게 밀집시키지 말고, 주제별로 자연스럽게 단락을 나누어 서술한다."""

        response = self.client.chat.completions.create(
            model="gpt-4o",  # 종합분석은 gpt-4o 사용 (안정적)
            messages=[
                {"role": "system", "content": "당신은 데이터 계약서 검증 전문가입니다. 구조화된 데이터를 사용자 친화적인 서술형 보고서로 변환하는 것이 당신의 역할입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )
        
        return response.choices[0].message.content.strip()
    
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
