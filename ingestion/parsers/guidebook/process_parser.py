# -*- coding: utf-8 -*-
"""
Markdown → Semantic JSON (조/해설/소제목 + 표 매핑)
--------------------------------------------------------
- 입력: page-*.md (Vision 모델 후처리된 Markdown)
- 규칙 기반 파서: LLM 호출 없음
- 계층: # (장) / ## (조) / ### (해설·소제목)
- 표(| ... |) 자동 감지 → content 유지 + table 매핑
- 출력: 지정 페이지 범위만 포함된 JSON
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# ========= 설정 =========
MD_DIR = Path(r"C:\Users\USER\Downloads\pdf-ocr-test - 복사본\markitdowntext\3_md_final")  # 📂 Markdown 폴더
PAGE_GLOB = "page-*.md"
PAGE_START = 90 # 시작 페이지 번호
PAGE_END   = 109
OUT_JSON = Path(r"C:\Users\USER\Downloads\pdf-ocr-test - 복사본\markitdowntext\parsed_90_109_table_1.json")
# ========================

RE_H = re.compile(r"^(#{1,6})\s+(.*)\s*$")
RE_ARTICLE_H2 = re.compile(r"^제\s*\d+\s*조\b")
RE_ENUM_TOP = re.compile(r"^([\u2460-\u2473]|[①-⑳]|(?:\(?\d+\)|\d+\.)|[가-힣]\.|[가-힣]\))\s+")
RE_SUP_REF = re.compile(r"<sup>(\d+)</sup>")
RE_SUP_DEF = re.compile(r"^<sup>(\d+)</sup>\s*(.+)")


# ✅ Markdown 표 블록(| ... |) → JSON 행렬 파서
def parse_markdown_table(md_text: str) -> List[Dict[str, Any]]:
    tables = []
    pattern = re.compile(r"((?:\|.*\|\n?)+)", re.MULTILINE)
    for block in pattern.findall(md_text):
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        headers = [h.strip() for h in lines[0].strip("|").split("|")]
        rows = []
        for row_line in lines[2:]:  # 헤더+구분선 제외
            cells = [c.strip() for c in row_line.strip("|").split("|")]
            if len(cells) != len(headers):
                continue
            rows.append(dict(zip(headers, cells)))
        if rows:
            tables.append({"headers": headers, "rows": rows})
    return tables


def normalize_line(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())

def is_blank(s: str) -> bool:
    return len(s.strip()) == 0

def looks_like_article_h2(text: str) -> bool:
    return bool(RE_ARTICLE_H2.search(text))


def flush_open_section(buf: Dict[str, Any], sections: List[Dict[str, Any]]):
    if buf.get("type") and buf.get("content_lines"):
        # ✅ content 조립 및 markdown code fence 제거
        content = "\n".join(buf["content_lines"]).strip()
        content = re.sub(r"^```(?:markdown)?|```$", "", content, flags=re.MULTILINE).strip()
        if not content:
            return

        tables = parse_markdown_table(content)

        # ✅ 표 분리 모드
        if tables:
            # ✅ 마지막 줄 개행 없는 표까지 완벽히 제거
            text_only = re.sub(r"((?:\|.*\|\n?)+)", "", content, flags=re.MULTILINE).strip()

            if text_only:
                sections.append({
                    "type": buf["type"],
                    "title": buf.get("title"),
                    "subtitle": buf.get("subtitle"),
                    "content": text_only,
                    "continued": bool(buf.get("continued", False)),
                    "ocr_missing": False
                })

            # ✅ 표만 별도 section으로 추가
            for t in tables:
                sections.append({
                    "type": "표",
                    "title": buf.get("title"),
                    "subtitle": buf.get("subtitle"),
                    "content": None,
                    "table": [t],
                    "continued": bool(buf.get("continued", False)),
                    "ocr_missing": False
                })

        else:
            # ✅ 표가 없을 때 일반 섹션 추가
            sections.append({
                "type": buf["type"],
                "title": buf.get("title"),
                "subtitle": buf.get("subtitle"),
                "content": content,
                "continued": bool(buf.get("continued", False)),
                "ocr_missing": False
            })

        # ✅ footnote_refs 있으면 마지막 섹션에 추가
        if "footnote_refs" in buf:
            sections[-1]["footnote_refs"] = buf["footnote_refs"]

    buf.clear()
    
def parse_md_page(md_text: str,
                  page_no: int,
                  prev_article_title: Optional[str],
                  prev_subtitle: Optional[str] = None) -> Dict[str, Any]:
    lines = md_text.splitlines()
    sections: List[Dict[str, Any]] = []
    current_article_title = None
    carry_subtitle = prev_subtitle
    have_seen_article_this_page = False
    open_buf: Dict[str, Any] = {}

    def start_new_section(sec_type: str, title: str, subtitle: Optional[str], continued: bool):
        flush_open_section(open_buf, sections)
        open_buf["type"] = sec_type
        open_buf["title"] = title
        open_buf["subtitle"] = subtitle
        open_buf["content_lines"] = []
        open_buf["continued"] = continued
        open_buf["footnote_refs"] = []

    carry_title = prev_article_title
    first_nonblank_seen = False

    first_line = next((l for l in lines if l.strip()), "")
    if carry_title and first_line and not first_line.strip().startswith("#"):
        # 이전 페이지의 조문/해설이 이어지는 경우로 간주
        start_new_section("해설", carry_title, carry_subtitle, True)
        open_buf["content_lines"].append(first_line)
        # 첫 줄이 이미 처리됐으므로 삭제 (중복 방지)
        lines = lines[1:]


    for raw in lines:
        line = raw.rstrip("\n")
        m = RE_H.match(line)
                # ✅ <sup>n</sup> 각주 참조 감지
        sup_refs = RE_SUP_REF.findall(line)
        if sup_refs:
            open_buf.setdefault("footnote_refs", [])
            open_buf["footnote_refs"].extend(map(int, sup_refs))

        if not sections and not open_buf.get("type") and not line.strip().startswith("#"):
            if carry_title:  # 이전 조문/해설이 있다면
                start_new_section("해설", carry_title, carry_subtitle, True)
                open_buf["content_lines"].append(line)
                continue

        # ✅ <sup>n</sup> 각주 정의 감지
        m_sup_def = RE_SUP_DEF.match(line.strip())
        if m_sup_def:
            sup_id = int(m_sup_def.group(1))
            sup_text = m_sup_def.group(2).strip()
            title_for_expl = current_article_title or carry_title
            sections.append({
                "type": "주석",
                "title": title_for_expl,
                "subtitle": f"참고자료 {sup_id}",
                "content": sup_text,
                "continued": True
            })
            continue

        # 표 해설 감지
        if (line.strip().startswith("- **") or line.strip().startswith("- ")) and sections:
            last_section = sections[-1]
            if last_section.get("table"):
                # 직전 섹션이 표를 가진 경우 → 새 해설 섹션으로 전환
                title_for_expl = last_section.get("title")
                subtitle = last_section.get("subtitle") or "표 해설"
                start_new_section("해설", title_for_expl, subtitle, True)
                open_buf["content_lines"].append(line)
                continue

        # ✅ 헤더가 아닌 일반 줄에서도 <예시 문구> 감지
        if re.search(r"<\s*예시\s*문구\s*\d*\s*>", line.strip()):
            title_for_expl = current_article_title or carry_title
            subtitle = line.strip().replace("<", "").replace(">", "").strip()
            start_new_section("해설", title_for_expl, subtitle, False)
            continue

        if m:
            hashes, text = m.group(1), m.group(2).strip()

            if len(hashes) == 2:  # ## 조문
                if looks_like_article_h2(text):
                    # 제n조면 조문으로 시작
                    current_article_title = text
                    have_seen_article_this_page = True
                    start_new_section("조", current_article_title, None, False)
                    continue

                # ✅ "## 02 데이터 제공형 해설" → 이전 해설의 연속으로 간주 (subtitle 유지)
                if re.match(r"^\d{1,2}\.?\s*데이터\s*(제공형|가공형|중개형)\s*해설", text):
                    title_for_expl = carry_title or current_article_title
                    subtitle = carry_subtitle  # ✅ 새로 갱신하지 않고 이전 subtitle 유지
                    start_new_section("해설", title_for_expl, subtitle, True)
                    continue

                elif re.search(r"<\s*예시\s*문구\s*\d*", text):
                    # ✅ 예시 문구 → 별도 해설 블록으로 처리
                    subtitle = text.replace("<", "").replace(">", "").strip()
                    title_for_expl = current_article_title or carry_title
                    start_new_section("해설", title_for_expl, subtitle, False)
                    continue

                else:
                    # ✅ NEW: 일반 해설 헤더 처리 (ex: ## 용어의 정의)
                    # carry_title과 text가 모두 '정의', '용어' 포함이면 이전 조문 해설의 연속으로 간주
                    if carry_title and re.search(r"(정의|용어)", carry_title) and re.search(r"(정의|용어)", text):
                        title_for_expl = carry_title
                        start_new_section("해설", title_for_expl, text, True)
                    else:
                        # 완전히 새로운 해설 대주제
                        current_topic_title = text
                        start_new_section("해설", current_topic_title, None, False)
                    continue


            elif len(hashes) == 3:  # ### 해설
                subtitle = text
                title_for_expl = current_article_title or carry_title
                cont = not have_seen_article_this_page and bool(title_for_expl)
                start_new_section("해설", title_for_expl, subtitle, cont)
                continue
            elif len(hashes) == 4:
                if RE_ARTICLE_H2.search(text):
                    # 기존 조문 fallback
                    current_article_title = text
                    have_seen_article_this_page = True
                    start_new_section("조", current_article_title, None, False)
                else:
                    # ✅ NEW: '###' 해설 밑의 '####'를 소제목으로 인식
                    subtitle = text
                    title_for_expl = current_article_title or carry_title
                    start_new_section("해설", title_for_expl, subtitle, False)
                continue

            else:
                flush_open_section(open_buf, sections)
                continue
            
        # ✅ NEW: 각주형 법령 블록 감지 ([^11]: 「데이터산업법」 제12조 ...)
        m_foot = re.match(r"\[\^(\d+)\]:\s*(.+)", line.strip())
        if m_foot:
            foot_num = m_foot.group(1)
            rest_text = m_foot.group(2)
            m_law = re.search(r"「([^」]{3,})법」", rest_text)
            law_name = m_law.group(1).strip() + "법" if m_law else f"법령각주{foot_num}"
            title_for_expl = current_article_title or carry_title

            start_new_section("법령", title_for_expl, law_name, True)
            open_buf["content_lines"].append(rest_text)
            continue


        # 굵은 텍스트(**...**) → 해설 subtitle
        bold_match = re.match(r"^\*\*(.+?)\*\*", line.strip())
        if bold_match:
            subtitle = bold_match.group(1).strip()
            title_for_expl = current_article_title or carry_title
            start_new_section("해설", title_for_expl, subtitle, False)
            continue
        

        if not first_nonblank_seen and carry_title:
            first_line = next((l for l in lines if l.strip()), "")
            # 만약 첫 줄이 "02", "데이터 제공형", "해설" 등으로 시작하면 이전 해설의 연속으로 간주
            if re.match(r"^(0?\d{1,2}|데이터|이용자|제공자|해설)", first_line.strip()):
                title_for_expl = carry_title
                subtitle_for_expl = carry_subtitle
                start_new_section("해설", title_for_expl, subtitle_for_expl, True)

                        
        # ✅ 법령 인용 감지 (단, 현재 조문 내부에서는 해설로 분리하지 않음)
        if re.search(r"「[^」]{3,}법」", line) and sections:
            last_section = sections[-1]
            # ⚠️ 현재 open_buf가 '조'면 해설로 전환하지 말고 그냥 본문으로 추가
            if open_buf.get("type") == "조":
                open_buf["content_lines"].append(line)
                continue

            # ✅ 조문이 아닌 경우(해설 등)에서만 새 섹션으로 분리
            title_for_expl = last_section.get("title") or carry_title
            subtitle = "관련 법령 해설"
            start_new_section("해설", title_for_expl, subtitle, True)
            open_buf["content_lines"].append(line)
            continue

        if not open_buf.get("type"):
            if RE_ENUM_TOP.match(line) and (current_article_title or carry_title):
                if not current_article_title:
                    current_article_title = carry_title
                start_new_section("조", current_article_title, None, True)
            else:
                continue

        if is_blank(line):
            if open_buf["content_lines"] and open_buf["content_lines"][-1] != "":
                open_buf["content_lines"].append("")
        else:
            open_buf["content_lines"].append(line)

    flush_open_section(open_buf, sections)

    last_subtitle_val = None
    if sections:
        for sec in reversed(sections):
            if sec.get("subtitle"):
                last_subtitle_val = sec["subtitle"]
                break

    return {
        "page_no": str(page_no),
        "sections": sections,
        "last_article_title": current_article_title or prev_article_title,
        "last_subtitle": last_subtitle_val,
    }



def load_pages(md_dir: Path, glob_pat: str) -> List[Path]:
    pages = sorted(md_dir.glob(glob_pat),
                   key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    return pages


def main():
    page_files = load_pages(MD_DIR, PAGE_GLOB)
    all_pages: List[Dict[str, Any]] = []
    flat_sections: List[Dict[str, Any]] = []

    prev_title: Optional[str] = None
    prev_subtitle: Optional[str] = None
    for p in page_files:
        m = re.search(r"(\d+)", p.stem)
        page_no = int(m.group(1)) if m else -1
        if not (PAGE_START <= page_no <= PAGE_END):
            continue


        md_text = p.read_text(encoding="utf-8", errors="ignore")
        parsed = parse_md_page(md_text, page_no, prev_title, prev_subtitle)
        prev_title = parsed["last_article_title"]
        prev_subtitle = parsed.get("last_subtitle")
        
        

        all_pages.append({"page_no": parsed["page_no"], "sections": parsed["sections"]})
        for sec in parsed["sections"]:
            flat_sections.append({
                "page_no": parsed["page_no"],
                "type": sec["type"],
                "title": sec["title"],
                "subtitle": sec.get("subtitle"),
                "text": sec["content"],
                "table": sec.get("table")  # ✅ 표 포함
            })

    out = {
        "meta": {"source": str(MD_DIR), "pages": f"{PAGE_START}-{PAGE_END}"},
        "sections": flat_sections
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Saved: {OUT_JSON} (pages={PAGE_START}-{PAGE_END}, sections={len(flat_sections)})")

if __name__ == "__main__":
    main()
