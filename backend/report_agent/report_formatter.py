"""
보고서 포맷터 모듈
JSON 형식의 최종 보고서를 마크다운 등 다양한 형식으로 변환
"""
from typing import Dict, Any, List
from datetime import datetime


class ReportFormatter:
    """보고서 형식 변환기"""
    
    def to_markdown(self, json_report: Dict[str, Any]) -> str:
        """
        JSON 보고서를 마크다운 형식으로 변환
        
        Args:
            json_report: step5_final_integrator에서 생성한 최종 보고서 JSON
            
        Returns:
            마크다운 형식의 보고서 문자열
        """
        lines = []
        
        # 헤더
        lines.append("# 데이터 표준계약 검증 보고서")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 기본 정보
        lines.append("## 📋 기본 정보")
        lines.append("")
        lines.append(f"- **계약서명**: {json_report.get('contract_name', 'N/A')}")
        lines.append(f"- **분류 유형**: {json_report.get('classification_type', 'N/A')}")
        lines.append(f"- **검증 일시**: {json_report.get('timestamp', 'N/A')}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 요약
        summary = json_report.get('summary', {})
        lines.append("## 📊 검증 요약")
        lines.append("")
        lines.append(f"### 전체 점수: {summary.get('overall_score', 0)}/100")
        lines.append("")
        lines.append("| 항목 | 점수 |")
        lines.append("|------|------|")
        lines.append(f"| 완전성 | {summary.get('completeness_score', 0)}/100 |")
        lines.append(f"| 체크리스트 준수 | {summary.get('checklist_score', 0)}/100 |")
        lines.append(f"| 내용 충실도 | {summary.get('content_score', 0)}/100 |")
        lines.append("")
        
        # 주요 발견사항
        if summary.get('key_findings'):
            lines.append("### 주요 발견사항")
            lines.append("")
            for finding in summary['key_findings']:
                lines.append(f"- {finding}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 완전성 검증 (A1)
        a1_result = json_report.get('completeness_validation', {})
        lines.append("## 1️⃣ 완전성 검증 (A1)")
        lines.append("")
        lines.append(f"**점수**: {a1_result.get('score', 0)}/100")
        lines.append("")
        
        # 매칭된 조항
        matched = a1_result.get('matched_articles', [])
        if matched:
            lines.append(f"### ✅ 매칭된 조항 ({len(matched)}개)")
            lines.append("")
            import re
            for article in matched[:5]:  # 상위 5개만
                user_title = article.get('user_article_title', 'N/A')
                std_title = article.get('std_article_title', 'N/A')
                
                # URN ID 제거
                std_title = re.sub(r'\s*\(urn:[^)]+\)', '', std_title)
                
                lines.append(f"- **{user_title}** ↔ {std_title}")
                lines.append(f"  - 유사도: {article.get('similarity_score', 0):.2f}")
            if len(matched) > 5:
                lines.append(f"- ... 외 {len(matched) - 5}개")
            lines.append("")
        
        # 누락된 조항
        missing = a1_result.get('missing_articles', [])
        if missing:
            lines.append(f"### ⚠️ 누락된 조항 ({len(missing)}개)")
            lines.append("")
            for article in missing:
                # URN ID 제거하고 제목만 표시
                title = article.get('std_article_title', 'N/A')
                # (urn:...) 패턴 제거
                import re
                title = re.sub(r'\s*\(urn:[^)]+\)', '', title)
                
                lines.append(f"- **{title}**")
                lines.append(f"  - 중요도: {article.get('importance', 'N/A')}")
                if article.get('recommendation'):
                    lines.append(f"  - 권장사항: {article['recommendation']}")
            lines.append("")
        
        # 추가된 조항
        extra = a1_result.get('extra_articles', [])
        if extra:
            lines.append(f"### ➕ 추가된 조항 ({len(extra)}개)")
            lines.append("")
            for article in extra:
                lines.append(f"- **{article.get('user_article_title', 'N/A')}**")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 체크리스트 검증 (A2)
        a2_result = json_report.get('checklist_validation', {})
        lines.append("## 2️⃣ 체크리스트 검증 (A2)")
        lines.append("")
        lines.append(f"**점수**: {a2_result.get('score', 0)}/100")
        lines.append("")
        
        checklist_items = a2_result.get('checklist_results', [])
        if checklist_items:
            # 통과/실패 통계
            passed = sum(1 for item in checklist_items if item.get('status') == 'pass')
            failed = sum(1 for item in checklist_items if item.get('status') == 'fail')
            warning = sum(1 for item in checklist_items if item.get('status') == 'warning')
            
            lines.append(f"- ✅ 통과: {passed}개")
            lines.append(f"- ❌ 실패: {failed}개")
            lines.append(f"- ⚠️ 경고: {warning}개")
            lines.append("")
            
            # 실패 항목 상세
            if failed > 0:
                lines.append("### ❌ 실패 항목")
                lines.append("")
                for item in checklist_items:
                    if item.get('status') == 'fail':
                        lines.append(f"- **{item.get('item_title', 'N/A')}**")
                        lines.append(f"  - 사유: {item.get('reason', 'N/A')}")
                        if item.get('recommendation'):
                            lines.append(f"  - 권장사항: {item['recommendation']}")
                lines.append("")
            
            # 경고 항목
            if warning > 0:
                lines.append("### ⚠️ 경고 항목")
                lines.append("")
                for item in checklist_items:
                    if item.get('status') == 'warning':
                        lines.append(f"- **{item.get('item_title', 'N/A')}**")
                        lines.append(f"  - 사유: {item.get('reason', 'N/A')}")
                lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 내용 분석 (A3)
        a3_result = json_report.get('content_analysis', {})
        lines.append("## 3️⃣ 내용 분석 (A3)")
        lines.append("")
        lines.append(f"**점수**: {a3_result.get('score', 0)}/100")
        lines.append("")
        
        content_items = a3_result.get('article_comparisons', [])
        if content_items:
            # 충실도 통계
            high = sum(1 for item in content_items if item.get('fidelity_level') == 'high')
            medium = sum(1 for item in content_items if item.get('fidelity_level') == 'medium')
            low = sum(1 for item in content_items if item.get('fidelity_level') == 'low')
            
            lines.append(f"- 🟢 높음: {high}개")
            lines.append(f"- 🟡 보통: {medium}개")
            lines.append(f"- 🔴 낮음: {low}개")
            lines.append("")
            
            # 낮은 충실도 항목
            if low > 0:
                lines.append("### 🔴 충실도가 낮은 조항")
                lines.append("")
                for item in content_items:
                    if item.get('fidelity_level') == 'low':
                        lines.append(f"- **{item.get('article_title', 'N/A')}**")
                        lines.append(f"  - 충실도 점수: {item.get('fidelity_score', 0)}/100")
                        if item.get('issues'):
                            lines.append(f"  - 문제점: {', '.join(item['issues'])}")
                        if item.get('recommendation'):
                            lines.append(f"  - 권장사항: {item['recommendation']}")
                lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 종합 권장사항
        recommendations = json_report.get('recommendations', [])
        if recommendations:
            lines.append("## 💡 종합 권장사항")
            lines.append("")
            for i, rec in enumerate(recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 푸터
        lines.append("## 📌 참고사항")
        lines.append("")
        lines.append("- 본 보고서는 AI 기반 자동 분석 결과입니다.")
        lines.append("- 최종 검토는 법률 전문가와 함께 진행하시기 바랍니다.")
        lines.append("- 점수는 표준계약서 대비 상대적 평가입니다.")
        lines.append("")
        lines.append(f"*보고서 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        
        return "\n".join(lines)
