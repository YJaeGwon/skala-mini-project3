"""[개선1] runbook RAG — runbook 문서를 '제목' + '단계별' 조각으로 나눈다.

Base는 runbook 본문을 검색하지 않고, 모니터링 알림 문구에 'cpu', 'memory' 같은 키워드가
있는지만 보고 장애 유형을 골랐다. 여기서는 runbook 자체를 임베딩해 두고 증상(알림·로그·
사용자 설명)과 의미가 가까운 runbook을 찾는다. 조각마다 incident_type을 메타데이터로 붙여
검색 결과를 장애 유형 단위로 다시 합친다. 새 runbook 파일을 넣기만 하면 코드 수정 없이 검색된다.
"""
import re
from pathlib import Path

STEP_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")


def parse_runbook(text: str, incident_type: str) -> list[dict]:
    lines = text.strip().splitlines()
    title = lines[0].lstrip("# ").strip()
    chunks = [{"chunk_id": f"{incident_type}#0", "incident_type": incident_type, "title": title,
               "text": title}]
    for line in lines[1:]:
        m = STEP_RE.match(line)
        if m:
            chunks.append({"chunk_id": f"{incident_type}#{m.group(1)}", "incident_type": incident_type,
                           "title": title, "text": f"{title}\n{m.group(2)}"})
    return chunks


def load_chunks(runbook_dir: Path) -> tuple[list[dict], dict[str, str]]:
    """반환: (chunks, {incident_type: 제목})."""
    chunks, titles = [], {}
    for path in sorted(runbook_dir.glob("*.md")):
        parsed = parse_runbook(path.read_text(), path.stem)
        titles[path.stem] = parsed[0]["title"]
        chunks.extend(parsed)
    return chunks, titles
