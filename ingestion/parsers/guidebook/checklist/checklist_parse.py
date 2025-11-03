# -*- coding: utf-8 -*-
"""
Markdown → Semantic JSON (조/해설/소제목 + 표 매핑 + 페이지 간 구분 상속)
------------------------------------------------------------------------
- Vision 모델 후처리 Markdown을 규칙 기반으로 JSON 구조화
- 표(| ... |) 자동 감지 및 JSON 매핑
- 페이지 넘어가도 '구분' 열(예: 데이터 거래 중개 관련)이 자동 상속됨
- "제x장 ..." / "┃표 n┃ ..." 구조 정확히 인식
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# ========= 설정 =========
MD_DIR = Path(r"C:\Users\USER\Downloads\pdf-ocr-test - 복사본\markitdowntext\3_md_final")
PAGE_GLOB = "page-*.md"
PAGE_START = 222
PAGE_END = 224
OUT_JSON = Path(r"C:\Users\USER\Downloads\pdf-ocr-test - 복사본\markitdowntext\parsed_222_224_table_1.json")
# ========================

RE_H = re.compile(r"^(#{1,6})\s+(.*)\s*$")
RE_ARTICLE_H2 = re.compile(r"^제\s*\d+\s*조\b")

CANON_HEADERS = ["구분", "주요 항목", "확인사항", "확인", "관련조항"]


# ------------------------------------------------------------
# 1️⃣ Markdown 내 표 파서
# ------------------------------------------------------------
def parse_markdown_table(md_text: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Markdown 내 | ... | 형식 표를 탐지해 JSON으로 변환.
    - 표 간 구분선 무시
    - 5열 강제 정규화
    - 구분, 주요항목, 관련조항 상속
    """
    tables = []
    last_group_overall = None
    blocks = re.findall(r"((?:\|.*\|\n?)+)", md_text)

    for block in blocks:
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        if not lines:
            continue

        # header & data 분리
        header = [c.strip() for c in lines[0].strip("|").split("|")]
        if len(header) != 5 or not any("구분" in h for h in header):
            header = CANON_HEADERS[:]

        rows = []
        last_group = last_item = last_ref = None

        for ln in lines[1:]:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if all(re.fullmatch(r"[-─—_]+", c) or not c for c in cells):
                continue
            if len(cells) < 5:
                cells += [""] * (5 - len(cells))
            elif len(cells) > 5:
                cells = cells[:5]

            row = dict(zip(CANON_HEADERS, cells))

            # 빈 칸 상속
            if not row["구분"]:
                row["구분"] = last_group or ""
            if not row["주요 항목"]:
                row["주요 항목"] = last_item or ""
            if not row["관련조항"]:
                row["관련조항"] = last_ref or ""

            rows.append(row)
            if row["구분"].strip():
                last_group = row["구분"].strip()
                last_group_overall = last_group
            if row["주요 항목"].strip():
                last_item = row["주요 항목"].strip()
            if row["관련조항"].strip():
                last_ref = row["관련조항"].strip()

        if rows:
            tables.append({
                "headers": CANON_HEADERS,
                "rows": rows
            })

    return tables, last_group_overall


# ------------------------------------------------------------
# 2️⃣ 현재 섹션을 sections 리스트에 추가
# ------------------------------------------------------------
def flush_open_section(buf: Dict[str, Any], sections: List[Dict[str, Any]]):
    if not buf.get("type") or not buf.get("content_lines"):
        return
    content = "\n".join(buf["content_lines"]).strip()
    if not content:
        return

    tables, last_group = parse_markdown_table(content)
    buf["last_group"] = last_group

    if tables:
        sections.append({
            "type": "표",
            "title": buf.get("title"),
            "subtitle": buf.get("subtitle"),
            "text": None,
            "table": tables
        })
    else:
        sections.append({
            "type": buf["type"],
            "title": buf.get("title"),
            "subtitle": buf.get("subtitle"),
            "text": content,
            "table": None
        })
    buf.clear()


# ------------------------------------------------------------
# 3️⃣ 페이지 단위 Markdown 파서
# ------------------------------------------------------------
def parse_md_page(md_text: str, page_no: int, prev_title: Optional[str]) -> Dict[str, Any]:
    lines = md_text.splitlines()
    sections = []
    buf = {}
    current_title = None
    last_table_title = None

    # 🔹 최근 만난 헤딩을 기억
    last_h2 = None
    last_h3 = None

    def start_section(sec_type, title, subtitle):
        flush_open_section(buf, sections)
        buf["type"] = sec_type
        buf["title"] = title
        buf["subtitle"] = subtitle
        buf["content_lines"] = []

    carry_title = prev_title

    for raw in lines:
        line = raw.rstrip("\n")

        # ✅ (1) ┃표 19┃ 라인 완전 정제 + 탐지
        line_clean = re.sub(r"[#`]", "", line)
        line_clean = re.sub(r"\|+\s*---\s*\|+", "", line_clean)
        line_clean = re.sub(r"^\s*\|+\s*|\s*\|+\s*$", "", line_clean)
        line_clean = line_clean.strip()

        if re.search(r"┃표\s*\d+┃", line_clean):
            clean = re.sub(r"^\s*\|?\s*", "", line_clean)
            clean = re.sub(r"\s*\|?\s*$", "", clean).strip()

            # ✅ 표 시작 시, '바로 직전의 H3'를 subtitle로 채운다
            current_title = clean
            carry_title = None
            start_section("표", clean, last_h3)   # ← ★ 여기!
            last_table_title = clean
            continue

        # ✅ (2) 헤더 감지
        m = RE_H.match(line)
        if m:
            hashes, text = m.groups()

            # 헤더 텍스트 내 '┃표 n┃' 감지 → 강제 표 섹션
            if re.search(r"┃표\s*\d+┃", text):
                clean = re.sub(r"^\s*#+\s*\|?\s*", "", text)
                clean = re.sub(r"\s*\|?\s*$", "", clean).strip()
                # 최근 H3를 subtitle로 사용
                flush_open_section(buf, sections)
                start_section("표", clean, last_h3)  # ← ★ 여기!
                last_table_title = clean
                continue

            # 헤더 레벨별 처리
            if len(hashes) == 2:  # ## H2
                last_h2 = text
                # 기존 로직 유지: 표 제목 직후에 H2가 나오면 그걸 subtitle로
                if last_table_title:
                    # 직전 표 섹션이 아직 버퍼에 있을 수 있으므로 버퍼 상태 반영
                    if buf.get("type") == "표" and buf.get("subtitle") in (None, "") and buf.get("title") == last_table_title:
                        buf["subtitle"] = text
                        last_table_title = None
                        # 이어지는 내용이 표 본문이 아닐 수 있어 해설 시작
                        start_section("해설", current_title, None)
                    else:
                        start_section("표", last_table_title, text)
                        last_table_title = None
                else:
                    current_title = text
                    start_section("해설", current_title, None)
                continue

            elif len(hashes) == 3:  # ### H3
                last_h3 = text

                # 🔥 보정: 방금 전 만든 "표" 섹션에 subtitle이 비어있으면 이 H3를 붙여준다
                if sections and sections[-1].get("type") == "표" and not sections[-1].get("subtitle"):
                    sections[-1]["subtitle"] = text
                    # 이 H3는 표의 부제였으니 별도 해설 섹션은 시작하지 않고 다음 줄 처리
                    continue

                # 일반 해설 섹션 시작
                start_section("해설", current_title or carry_title, text)
                continue

        # ✅ (3) 기본 해설 라인
        if not buf.get("type"):
            start_section("해설", current_title or carry_title, None)

        buf.setdefault("content_lines", []).append(line)

    flush_open_section(buf, sections)

    # ... 이하 동일 (last_group 탐색/리턴부 유지)

    # ✅ 마지막 구분 carry
    last_group = None
    for sec in reversed(sections):
        if sec.get("type") == "표" and sec.get("table"):
            for t in reversed(sec["table"]):
                for r in reversed(t["rows"]):
                    if r.get("구분") and r["구분"].strip():
                        last_group = r["구분"].strip()
                        break
                if last_group:
                    break
        if last_group:
            break

    return {
        "page_no": str(page_no),
        "sections": sections,
        "last_article_title": current_title or prev_title,
        "last_group": last_group,
        "last_h3": last_h3     # ✅ 추가
    }


# ------------------------------------------------------------
# 4️⃣ 파일 로드 및 페이지 carry 처리
# ------------------------------------------------------------
def load_pages(md_dir: Path, glob_pat: str) -> List[Path]:
    return sorted(md_dir.glob(glob_pat), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))


def main():
    page_files = load_pages(MD_DIR, PAGE_GLOB)
    flat_sections = []
    prev_title = None
    prev_group = None
    prev_h3 = None

    for p in page_files:
        m = re.search(r"(\d+)", p.stem)
        page_no = int(m.group(1)) if m else -1
        if not (PAGE_START <= page_no <= PAGE_END):
            continue

        md_text = p.read_text(encoding="utf-8", errors="ignore")
        parsed = parse_md_page(md_text, page_no, prev_title)
        prev_title = parsed["last_article_title"]
        if parsed.get("last_h3"):
            prev_h3 = parsed["last_h3"]

        for sec in parsed["sections"]:
                # ✅ subtitle 보정
            if sec["type"] == "표" and not sec.get("subtitle"):
                if prev_h3:
                    sec["subtitle"] = prev_h3
            if sec["type"] == "표" and sec.get("table"):
                for t in sec["table"]:
                    for r in t["rows"]:
                        # 이전 페이지의 구분 carry
                        if not r.get("구분") or r["구분"].strip("- ") == "":
                            if prev_group:
                                r["구분"] = prev_group
                        if r.get("구분") and r["구분"].strip():
                            prev_group = r["구분"].strip()

            flat_sections.append({
                "page_no": parsed["page_no"],
                "type": sec["type"],
                "title": sec["title"],
                "subtitle": sec.get("subtitle"),
                "text": sec.get("text"),
                "table": sec.get("table")
            })

        if parsed.get("last_group"):
            prev_h3 = parsed["last_h3"]
            prev_group = parsed["last_group"]

    out = {
        "meta": {"source": str(MD_DIR), "pages": f"{PAGE_START}-{PAGE_END}"},
        "sections": flat_sections
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Saved: {OUT_JSON} (pages={PAGE_START}-{PAGE_END}, sections={len(flat_sections)})")


if __name__ == "__main__":
    main()
