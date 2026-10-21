"""Before 서버 준비 — 원본 Base 코드를 '그대로' 복사하고 데이터만 개선판과 같게 맞춘다.

비교 조건: 코드는 원본(all_total_vue_student) 그대로, 입력 데이터(모니터링·runbook)는 동일.
원본 폴더는 건드리지 않는다. 복사 후 .py/.html 파일이 원본과 바이트 단위로 같은지 검사한다.
"""
import filecmp
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT.parent / "all_total_vue_student"
SNAPSHOT = Path(__file__).resolve().parent / "_before_snapshot"


def prepare() -> Path:
    if SNAPSHOT.exists():
        shutil.rmtree(SNAPSHOT)
    shutil.copytree(ORIGINAL, SNAPSHOT, ignore=shutil.ignore_patterns(
        ".venv", ".env", "session.db", "doc", "__pycache__", ".DS_Store", "data"))
    (SNAPSHOT / "data" / "runbooks").mkdir(parents=True)
    shutil.copy(ROOT / "data" / "monitoring.json", SNAPSHOT / "data" / "monitoring.json")
    for rb in (ROOT / "data" / "runbooks").glob("*.md"):
        shutil.copy(rb, SNAPSHOT / "data" / "runbooks" / rb.name)
    code = [p for p in ORIGINAL.rglob("*") if p.suffix in (".py", ".html") and ".venv" not in p.parts]
    for p in code:
        if not filecmp.cmp(p, SNAPSHOT / p.relative_to(ORIGINAL), shallow=False):
            raise RuntimeError(f"Before 스냅샷 코드가 원본과 다릅니다: {p}")
    return SNAPSHOT


if __name__ == "__main__":
    print(f"준비 완료: {prepare()} (원본 코드 그대로 + 동일 데이터)")
