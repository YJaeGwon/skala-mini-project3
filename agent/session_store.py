"""Wave 12 — 프로세스 밖(SQLite 파일)에 두는 세션 저장소. + [추가3] 요약 메모리 테이블.

서버가 재시작돼도(새 프로세스, 새 인스턴스) 같은 session.db 파일을 다시 열므로
대화 이력이 유지된다. in-memory dict였다면 재시작 즉시 소실됐을 상태다.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "session.db"


class SqliteSessionStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            " thread_id TEXT, role TEXT, content TEXT, created TEXT)"
        )
        # [추가3] 오래된 대화를 LLM으로 요약해 저장해 둔다 — covered = 요약에 포함된 메시지 수
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS summaries ("
            " thread_id TEXT PRIMARY KEY, summary TEXT, covered INTEGER)"
        )
        self.conn.commit()

    def load_summary(self, thread_id: str) -> tuple[str, int]:
        row = self.conn.execute("SELECT summary, covered FROM summaries WHERE thread_id=?",
                                (thread_id,)).fetchone()
        return (row[0], row[1]) if row else ("", 0)

    def save_summary(self, thread_id: str, summary: str, covered: int) -> None:
        self.conn.execute("INSERT OR REPLACE INTO summaries VALUES (?,?,?)",
                          (thread_id, summary, covered))
        self.conn.commit()

    def load(self, thread_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE thread_id=? ORDER BY rowid",
            (thread_id,),
        ).fetchall()
        return [{"role": r, "content": c} for r, c in rows]

    def append(self, thread_id: str, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?)",
            (thread_id, role, content, datetime.now().isoformat()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
