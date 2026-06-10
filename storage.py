import sqlite3
from pathlib import Path


class ItemStorage:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_items (
                item_id INTEGER PRIMARY KEY,
                seen_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def is_seen(self, item_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        return row is not None

    def mark_seen(self, item_id: int, seen_at: float) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_items (item_id, seen_at) VALUES (?, ?)",
            (item_id, seen_at),
        )
        self._conn.commit()

    def mark_many_seen(self, items: list[tuple[int, float]]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO seen_items (item_id, seen_at) VALUES (?, ?)",
            items,
        )
        self._conn.commit()

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM seen_items").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self._conn.close()
