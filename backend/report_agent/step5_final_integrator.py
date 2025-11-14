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
                 a2_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        체크리스트 결과를 통합하여 최종 보고서 생성
        
        Args:
            step4_result: Step 4 결과 (포맷팅된 보고서)
            a2_result: A2 체크리스트 검증 결과 (None 가능)
            
        Returns:
            최종 통합 보고서 JSON
        """
        logger.info("Step 5 최종 통합 시작")
        
        # Step4 결과 복사
        final_report = step4_result.copy()
        
        # A2 결과 확인
        if not a2_result:
            logger.warning("A2 체크리스트 결과가 없습니다. 체크리스트 통합 스킵")
            final_report["checklist_summary"] = {
                "total_items": 0,
                "passed_items": 0,
                "failed_items": 0,
                "unclear_items": 0,
                "manual_check_items": 0,
                "pass_rate": 0.0
            }
        else:
            # 체크리스트 결과 통합
            final_report["user_articles"] = self._integrate_checklist_results(
                step4_result.get("user_articles", []),
                a2_result
            )
            
            # 체크리스트 통계 추가
            final_report["checklist_summary"] = self._calculate_checklist_summary(a2_result)
            
            logger.info(f"체크리스트 통합 완료: {len(a2_result.get('matched_articles', []))}개 조항")
        
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
                
                # 이 표준 조항에 매칭된 모든 사용자 조항에 체크리스트 추가
                for user_info in matched_users:
                    user_article_no = user_info.get("user_article_no")
                    if user_article_no is not None:
                        if user_article_no not in a2_by_article:
                            a2_by_article[user_article_no] = []
                        
                        # 체크리스트 항목 추가 (중복 방지)
                        a2_by_article[user_article_no].extend(checklist_results)
            
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
        user_article_title = article_data.get('user_article_title', 'N/A')
        matched_standards = article_data.get('matched_standard_articles', [])
        insufficient_items = article_data.get('insufficient_items', [])
        missing_items = article_data.get('missing_items', [])
        checklist_results = article_data.get('checklist_results', [])
        
        # 프롬프트 구성
        prompt = f"""당신은 데이터 계약서 검증 전문가입니다. 아래 구조화된 검증 데이터를 바탕으로 사용자가 이해하기 쉬운 서술형 보고서를 작성해주세요.

## 검증 대상 조항
{user_article_title}

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
- 동일한 스타일과 톤을 모든 조항에 대해 일관되게 유지한다."""

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
