"""检索索引仓库：负责 chunk 落库、FTS5/稀疏向量/RRF 混合检索与谱系追踪。"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from feishu_agent.database.db import Database, iso_now
from feishu_agent.index import INDEX_VERSION
from feishu_agent.index.chunker import build_chunks, message_indexable
from feishu_agent.index.graph import (
    entity_id,
    extract_message_entities,
    reply_to_message_id,
)
from feishu_agent.index.tokenizer import (
    encode_token,
    tokenize,
    tokenize_search_text,
    token_counts,
)

RRF_K = 60
MAX_QUERY_TOKENS = 64
FTS_CANDIDATE_LIMIT = 500
MAX_RESULT_LIMIT = 50
MAX_EVIDENCE_CHARS = 300

_HEX_ID_RE = re.compile(r"^[0-9a-f]{64}$")


class IndexRepository:
    """SQLite 派生索引仓库：chunk、FTS5、稀疏向量、知识图谱与运行审计。"""

    def __init__(self, db: Database) -> None:
        # 注入数据库实例；每轮索引的计数在执行时分别初始化。
        self.db = db

    # 返回索引版本、覆盖量、最近运行与新鲜度判断。
    def status(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            last_run = conn.execute(
                "SELECT * FROM index_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            latest_change = conn.execute(
                "SELECT MAX(changed_at) AS ts FROM message_versions"
            ).fetchone()["ts"]
            counts = {
                "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "chunk_messages": conn.execute(
                    "SELECT COUNT(*) FROM chunk_messages"
                ).fetchone()[0],
                "vectors": conn.execute(
                    "SELECT COUNT(*) FROM chunk_vectors"
                ).fetchone()[0],
                "fts_rows": conn.execute(
                    "SELECT COUNT(*) FROM chunks_fts"
                ).fetchone()[0],
                "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                "entity_mentions": conn.execute(
                    "SELECT COUNT(*) FROM entity_mentions"
                ).fetchone()[0],
                "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            }
            runs_total = conn.execute(
                "SELECT COUNT(*) FROM index_runs"
            ).fetchone()[0]
            last = self._decode_run(last_run) if last_run else None
            fresh = bool(
                last
                and not last.get("errors")
                and (latest_change is None or last["finished_at"] >= latest_change)
            )
            return {
                "version": INDEX_VERSION,
                "indexed": last is not None,
                "runs_total": runs_total,
                "last_run": last,
                "counts": counts,
                "latest_message_changed_at": latest_change,
                "fresh": fresh,
            }
        finally:
            conn.close()

    # 返回待索引的群列表，默认剔除外部群并可叠加白名单过滤。
    def list_chats_for_index(
        self,
        *,
        allow_external: bool = False,
        chat_ids: list[str] | None = None,
        allowed_chat_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            sql = "SELECT chat_id, name, external FROM chats"
            where: list[str] = []
            params: list[Any] = []
            if not allow_external:
                where.append("external = 0")
            if chat_ids:
                where.append(f"chat_id IN ({', '.join('?' * len(chat_ids))})")
                params.extend(chat_ids)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY chat_id"
            rows = conn.execute(sql, params).fetchall()
            allowed = set(allowed_chat_ids) if allowed_chat_ids is not None else None
            return [
                dict(row)
                for row in rows
                if allowed is None or row["chat_id"] in allowed
            ]
        finally:
            conn.close()

    # 全量重建：清空派生数据后逐群重算 chunk、向量与图谱。
    def rebuild(
        self,
        *,
        allow_external: bool = False,
        chat_ids: list[str] | None = None,
        allowed_chat_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        selected = self.list_chats_for_index(
            allow_external=allow_external,
            chat_ids=chat_ids,
            allowed_chat_ids=allowed_chat_ids,
        )
        started = datetime.now().astimezone()
        rebuild_id = uuid.uuid4().hex
        totals = self._empty_counts()
        errors: list[dict[str, str]] = []
        self._clear_derived()
        indexed_chat_ids: list[str] = []
        for chat in selected:
            chat_id = str(chat["chat_id"])
            indexed_chat_ids.append(chat_id)
            try:
                counts = self._rebuild_chat(chat_id, str(chat.get("name") or ""))
                self._add_counts(totals, counts)
                totals["chats_indexed"] += 1
            except Exception as exc:
                errors.append({"chat_id": chat_id, "error": str(exc)})
        totals["chats_failed"] = len(errors)
        scope = {"allow_external": bool(allow_external), "chat_ids": chat_ids or []}
        run_id = self._record_run(
            started=started,
            mode="rebuild",
            rebuild_id=rebuild_id,
            scope=scope,
            indexed_chat_ids=indexed_chat_ids,
            totals=totals,
            errors=errors,
        )
        return {
            "mode": "rebuild",
            "run_id": run_id,
            "rebuild_id": rebuild_id,
            "chats_indexed": totals["chats_indexed"],
            "chats_failed": totals["chats_failed"],
            "messages_scanned": totals["messages_scanned"],
            "messages_indexed": totals["messages_indexed"],
            "messages_skipped": totals["messages_skipped"],
            "chunks_created": totals["chunks_created"],
            "vectors_created": totals["vectors_created"],
            "entities_created": totals["entities_created"],
            "edges_created": totals["edges_created"],
            "errors": errors,
            "scope": scope,
        }

    # 增量索引：根据版本游标找出变化群并刷新对应派生数据。
    def incremental(
        self,
        *,
        chat_ids: list[str] | None = None,
        allowed_chat_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        last = self._last_run_decoded()
        if last is None:
            return {
                "mode": "incremental",
                "built": False,
                "reason": "no_rebuild_yet",
                "chats_changed": 0,
            }
        scope = last.get("scope") or {}
        allow_external = bool(scope.get("allow_external"))
        selected = self.list_chats_for_index(
            allow_external=allow_external,
            chat_ids=chat_ids,
            allowed_chat_ids=allowed_chat_ids,
        )
        if not selected:
            return {
                "mode": "incremental",
                "built": False,
                "reason": "no_chats_in_scope",
                "chats_changed": 0,
            }
        changed = self._changed_chat_ids(
            last.get("version_cursor"), [c["chat_id"] for c in selected]
        )
        indexed = self._indexed_chat_ids()
        targets = {
            str(chat["chat_id"]): chat
            for chat in selected
            if str(chat["chat_id"]) in changed or str(chat["chat_id"]) not in indexed
        }
        if not targets:
            return {
                "mode": "incremental",
                "built": False,
                "reason": "no_changes",
                "chats_changed": 0,
            }

        started = datetime.now().astimezone()
        totals = self._empty_counts()
        errors: list[dict[str, str]] = []
        rebuilt_ids: list[str] = []
        for chat_id, chat in targets.items():
            rebuilt_ids.append(chat_id)
            try:
                counts = self._rebuild_chat(chat_id, str(chat.get("name") or ""))
                self._add_counts(totals, counts)
                totals["chats_indexed"] += 1
            except Exception as exc:
                errors.append({"chat_id": chat_id, "error": str(exc)})
        totals["chats_failed"] = len(errors)
        run_id = self._record_run(
            started=started,
            mode="incremental",
            rebuild_id=last.get("rebuild_id") or "",
            scope=scope,
            indexed_chat_ids=rebuilt_ids,
            totals=totals,
            errors=errors,
        )
        return {
            "mode": "incremental",
            "built": True,
            "run_id": run_id,
            "rebuild_id": last.get("rebuild_id"),
            "chats_changed": len(targets),
            "chats_indexed": totals["chats_indexed"],
            "chats_failed": totals["chats_failed"],
            "messages_scanned": totals["messages_scanned"],
            "messages_indexed": totals["messages_indexed"],
            "messages_skipped": totals["messages_skipped"],
            "chunks_created": totals["chunks_created"],
            "vectors_created": totals["vectors_created"],
            "entities_created": totals["entities_created"],
            "edges_created": totals["edges_created"],
            "errors": errors,
            "scope": scope,
        }

    # 一致性校验：逐群比对消息覆盖、哈希和派生表计数。
    def consistency(
        self,
        *,
        allow_external: bool = False,
        chat_ids: list[str] | None = None,
        allowed_chat_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        selected = self.list_chats_for_index(
            allow_external=allow_external,
            chat_ids=chat_ids,
            allowed_chat_ids=allowed_chat_ids,
        )
        conn = self._connect()
        try:
            per_chat: list[dict[str, Any]] = []
            for chat in selected:
                chat_id = str(chat["chat_id"])
                rows = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT message_id, chat_id, msg_type, sender_name,
                               content_normalized, deleted, normalize_error
                        FROM messages
                        WHERE chat_id = ?
                        ORDER BY create_time_ms, message_position, message_id
                        """,
                        (chat_id,),
                    )
                ]
                expected = [
                    row
                    for row in rows
                    if message_indexable(
                        row, include_system=False, skip_low_signal=True
                    )
                ]
                expected_ids = {row["message_id"] for row in expected}
                indexed_ids = {
                    str(row[0])
                    for row in conn.execute(
                        """
                        SELECT DISTINCT cm.message_id
                        FROM chunk_messages cm
                        JOIN chunks c ON c.id = cm.chunk_id
                        WHERE c.chat_id = ?
                        """,
                        (chat_id,),
                    )
                }
                missing = [
                    {"message_id": row["message_id"], "reason": "not_in_index"}
                    for row in expected
                    if row["message_id"] not in indexed_ids
                ]
                per_chat.append(
                    {
                        "chat_id": chat_id,
                        "chat_name": chat.get("name") or "",
                        "messages_total": len(rows),
                        "expected_indexable": len(expected),
                        "indexed": len(indexed_ids),
                        "missing": missing,
                        "consistent": len(expected_ids - indexed_ids) == 0
                        and len(indexed_ids - expected_ids) == 0,
                    }
                )

            chunks_total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            fts_total = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
            vector_total = conn.execute(
                "SELECT COUNT(*) FROM chunk_vectors"
            ).fetchone()[0]
            missing_fts = [
                int(row[0])
                for row in conn.execute(
                    """
                    SELECT id FROM chunks
                    WHERE NOT EXISTS (
                        SELECT 1 FROM chunks_fts
                        WHERE chunks_fts.rowid = chunks.id
                    )
                    """
                )
            ]
            missing_vectors = [
                int(row[0])
                for row in conn.execute(
                    """
                    SELECT id FROM chunks
                    WHERE NOT EXISTS (
                        SELECT 1 FROM chunk_vectors
                        WHERE chunk_vectors.chunk_id = chunks.id
                    )
                    """
                )
            ]
            orphan_messages = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT cm.chunk_id, cm.message_id,
                           c.chat_id AS chunk_chat_id,
                           m.chat_id AS message_chat_id
                    FROM chunk_messages cm
                    JOIN chunks c ON c.id = cm.chunk_id
                    LEFT JOIN messages m ON m.message_id = cm.message_id
                    WHERE m.message_id IS NULL OR m.chat_id != c.chat_id
                    """
                )
            ]
            last = self._last_run_decoded()
            latest_change = conn.execute(
                "SELECT MAX(changed_at) AS ts FROM message_versions"
            ).fetchone()["ts"]
            fresh = bool(
                last
                and not last.get("errors")
                and (latest_change is None or last["finished_at"] >= latest_change)
            )
            schema_ok = (
                chunks_total == fts_total == vector_total
                and not missing_fts
                and not missing_vectors
                and not orphan_messages
            )
            consistent = bool(selected) and all(item["consistent"] for item in per_chat) and schema_ok and fresh
            return {
                "consistent": consistent,
                "chats_checked": len(selected),
                "per_chat": per_chat,
                "schema": {
                    "chunks_total": chunks_total,
                    "fts_total": fts_total,
                    "vector_total": vector_total,
                    "missing_fts": missing_fts,
                    "missing_vectors": missing_vectors,
                    "orphan_messages": orphan_messages,
                },
                "freshness": {"latest_message_changed_at": latest_change, "fresh": fresh},
            }
        finally:
            conn.close()

    # 混合检索：融合 BM25 与稀疏 TF-IDF 的 RRF 排序并返回证据。
    def search(
        self,
        query: str,
        *,
        chat_ids: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        text = str(query or "").strip()
        limit = max(1, min(int(limit), MAX_RESULT_LIMIT))
        tokens = list(dict.fromkeys(tokenize(text)))[:MAX_QUERY_TOKENS]
        if not text or not tokens:
            return {
                "query": text,
                "chat_ids": chat_ids or [],
                "total": 0,
                "results": [],
                "error": "empty_query" if not text else "no_tokens",
            }
        chunks = self._chunk_rows(chat_ids)
        bm25 = self._bm25_ranked(tokens, set(chunks))
        tfidf = self._tfidf_ranked(tokens, chunks)
        fused = self._rrf([("bm25", bm25), ("tfidf", tfidf)])
        results: list[dict[str, Any]] = []
        for rank, (chunk_id, score, sources) in enumerate(fused[:limit], start=1):
            row = chunks[chunk_id]
            results.append(
                {
                    "rank": rank,
                    "chunk_id": chunk_id,
                    "chat_id": row["chat_id"],
                    "chat_name": row["chat_name"],
                    "topic_key": row["topic_key"],
                    "thread_id": row["thread_id"],
                    "message_count": row["message_count"],
                    "message_ids": json.loads(row["message_ids_json"]),
                    "message_id_start": row["message_id_start"],
                    "message_id_end": row["message_id_end"],
                    "sender_name": row["start_sender_name"] or "未知",
                    "create_time": row["start_create_time"],
                    "create_time_ms": row["start_create_time_ms"],
                    "score": round(score, 6),
                    "sources": sources,
                    "content": row["content"],
                    "messages": self._chunk_messages(chunk_id),
                }
            )
        return {
            "query": text,
            "chat_ids": chat_ids or [],
            "total": len(fused),
            "results": results,
        }

    # 汇总知识图谱实体、关系边与消息提及的统计。
    def entity_stats(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            totals = {
                "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                "entity_mentions": conn.execute(
                    "SELECT COUNT(*) FROM entity_mentions"
                ).fetchone()[0],
                "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            }
            by_type = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT entity_type, COUNT(*) AS entities,
                           COALESCE(SUM(occurrence), 0) AS mentions
                    FROM entities
                    GROUP BY entity_type
                    ORDER BY mentions DESC, entity_type
                    """
                )
            ]
            top = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT entity_id, entity_type, value, occurrence
                    FROM entities
                    ORDER BY occurrence DESC, value
                    LIMIT 10
                    """
                )
            ]
            return {"totals": totals, "by_type": by_type, "top": top}
        finally:
            conn.close()

    # 按类型/关键词/数量上限列出知识图谱实体。
    def list_entities(
        self,
        *,
        entity_type: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            where: list[str] = []
            params: list[Any] = []
            if entity_type:
                where.append("entity_type = ?")
                params.append(entity_type)
            if q:
                where.append("(value LIKE ? OR entity_id = ?)")
                params.extend([f"%{q}%", q])
            sql = "SELECT * FROM entities"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY occurrence DESC, value LIMIT ?"
            params.append(max(1, min(int(limit), 200)))
            return [dict(row) for row in conn.execute(sql, params)]
        finally:
            conn.close()

    # 按关键词或实体 id 查询实体、邻居与提及消息。
    def query_graph(
        self,
        entity_keyword: str,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        if _HEX_ID_RE.fullmatch(entity_keyword or ""):
            return self._graph_entity_by_id(entity_keyword, limit=limit)
        matches = self.list_entities(q=entity_keyword, limit=10)
        if not matches:
            return {"found": False, "error": "entity_not_found", "matches": []}
        if len(matches) == 1:
            return self._graph_entity_by_id(str(matches[0]["entity_id"]), limit=limit)
        return {
            "found": False,
            "ambiguous": True,
            "matches": matches,
            "message": "多个实体匹配，请用 entity_id 精确查询",
        }

    # 按精确 entity_id 定位实体并组装图谱视图。
    def _graph_entity_by_id(
        self,
        entity_keyword: str,
        *,
        limit: int,
    ) -> dict[str, Any]:
        conn = self._connect()
        try:
            entity_row = conn.execute(
                "SELECT * FROM entities WHERE entity_id = ?", (entity_keyword,)
            ).fetchone()
            if entity_row is None:
                return {"found": False, "error": "entity_not_found", "matches": []}
            neighbors = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT neighbor.entity_id, neighbor.entity_type,
                           neighbor.value, e.edge_type,
                           COUNT(*) AS links, ROUND(SUM(e.weight), 3) AS weight
                    FROM edges e
                    JOIN entities neighbor ON neighbor.entity_id = e.target_entity_id
                    WHERE e.source_entity_id = ?
                    GROUP BY neighbor.entity_id, neighbor.entity_type,
                             neighbor.value, e.edge_type
                    UNION ALL
                    SELECT neighbor.entity_id, neighbor.entity_type,
                           neighbor.value, e.edge_type,
                           COUNT(*) AS links, ROUND(SUM(e.weight), 3) AS weight
                    FROM edges e
                    JOIN entities neighbor ON neighbor.entity_id = e.source_entity_id
                    WHERE e.target_entity_id = ?
                    GROUP BY neighbor.entity_id, neighbor.entity_type,
                             neighbor.value, e.edge_type
                    ORDER BY weight DESC, links DESC
                    LIMIT ?
                    """,
                    (entity_keyword, entity_keyword, max(1, min(int(limit), 100))),
                )
            ]
            messages = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT em.message_id, m.chat_id, m.sender_name, m.create_time,
                           m.content_normalized
                    FROM entity_mentions em
                    JOIN messages m ON m.message_id = em.message_id
                    WHERE em.entity_id = ?
                    ORDER BY m.create_time_ms DESC
                    LIMIT 10
                    """,
                    (entity_keyword,),
                )
            ]
            return {
                "found": True,
                "entity": dict(entity_row),
                "neighbors": neighbors,
                "messages": messages,
            }
        finally:
            conn.close()

    # 把数据库 chunk 行规范化为检索用字典。
    def _chunk_rows(
        self,
        chat_ids: list[str] | None,
    ) -> dict[int, dict[str, Any]]:
        conn = self._connect()
        try:
            sql = """
                SELECT c.id, c.chat_id, c.thread_id, c.topic_key, c.chunk_seq,
                       c.message_id_start, c.message_id_end, c.message_count,
                       c.message_ids_json, c.content, c.search_text,
                       c.content_hash, c.start_time_ms, c.end_time_ms,
                       chats.name AS chat_name,
                       m.sender_name AS start_sender_name,
                       m.create_time AS start_create_time,
                       m.create_time_ms AS start_create_time_ms
                FROM chunks c
                JOIN chats ON chats.chat_id = c.chat_id
                LEFT JOIN messages m ON m.message_id = c.message_id_start
            """
            params: list[Any] = []
            if chat_ids:
                sql += f" WHERE c.chat_id IN ({', '.join('?' * len(chat_ids))})"
                params.extend(chat_ids)
            sql += " ORDER BY c.chat_id, c.chunk_seq"
            return {int(row["id"]): dict(row) for row in conn.execute(sql, params)}
        finally:
            conn.close()

    # 基于 FTS5 执行 BM25 全文检索，返回命中的 chunk 与消息。
    def _bm25_ranked(
        self,
        tokens: list[str],
        allowed_chunk_ids: set[int],
    ) -> list[int]:
        conn = self._connect()
        try:
            fts_query = " OR ".join(f'"{encode_token(token)}"' for token in tokens)
            rows = conn.execute(
                """
                SELECT rowid AS chunk_id
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, FTS_CANDIDATE_LIMIT),
            ).fetchall()
            return [
                int(row["chunk_id"])
                for row in rows
                if int(row["chunk_id"]) in allowed_chunk_ids
            ]
        finally:
            conn.close()

    # 基于稀疏词频向量计算 TF-IDF 相似度并排序候选 chunk。
    def _tfidf_ranked(
        self,
        tokens: list[str],
        chunks: dict[int, dict[str, Any]],
    ) -> list[int]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT chunk_id, term_freqs_json
                FROM chunk_vectors
                """
            ).fetchall()
        finally:
            conn.close()
        vectors: dict[int, Counter[str]] = {}
        for row in rows:
            chunk_id = int(row["chunk_id"])
            if chunk_id not in chunks:
                continue
            try:
                raw = json.loads(row["term_freqs_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                raw = {}
            vectors[chunk_id] = Counter(
                {str(key): int(value) for key, value in raw.items() if int(value) > 0}
            )
        n_docs = max(len(vectors), 1)
        df: Counter[str] = Counter()
        for vector in vectors.values():
            df.update(vector.keys())

        def weight(count: int, token: str) -> float:
            idf = math.log((n_docs + 1) / (df[token] + 1)) + 1.0
            return (1.0 + math.log(count)) * idf

        query_tf = Counter(tokens)
        query_weights = {token: weight(count, token) for token, count in query_tf.items()}
        query_norm = math.sqrt(sum(value * value for value in query_weights.values()))
        if query_norm <= 0:
            return []
        scored: list[tuple[float, int]] = []
        for chunk_id, vector in vectors.items():
            dot = 0.0
            doc_norm_sq = 0.0
            for token, count in vector.items():
                w = weight(count, token)
                doc_norm_sq += w * w
                qw = query_weights.get(token)
                if qw:
                    dot += qw * w
            if dot <= 0 or doc_norm_sq <= 0:
                continue
            scored.append((dot / (query_norm * math.sqrt(doc_norm_sq)), chunk_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [chunk_id for _, chunk_id in scored]

    @staticmethod
    # 使用 Reciprocal Rank Fusion 融合多路检索的排序结果。
    def _rrf(
        ranked_lists: list[tuple[str, list[int]]],
    ) -> list[tuple[int, float, list[str]]]:
        scores: dict[int, float] = {}
        sources: dict[int, list[str]] = {}
        for method, ranked in ranked_lists:
            for rank, chunk_id in enumerate(ranked, start=1):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (
                    RRF_K + rank
                )
                sources.setdefault(chunk_id, []).append(method)
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [
            (chunk_id, score, sources[chunk_id])
            for chunk_id, score in ordered
        ]

    # 读取一个 chunk 包含的源消息。
    def _chunk_messages(self, chunk_id: int) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT cm.line_seq, m.message_id, m.chat_id, m.sender_name,
                           m.create_time, m.create_time_ms, m.content_normalized
                    FROM chunk_messages cm
                    JOIN messages m ON m.message_id = cm.message_id
                    WHERE cm.chunk_id = ?
                    ORDER BY cm.line_seq
                    """,
                    (chunk_id,),
                )
            ]
        finally:
            conn.close()

    # 重建单个群：清空旧数据后重新切块并建立向量与图谱。
    def _rebuild_chat(self, chat_id: str, chat_name: str) -> dict[str, int]:
        conn = self._connect()
        try:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT message_id, chat_id, msg_type, content_normalized,
                           sender_name, thread_id, create_time, create_time_ms,
                           message_position, deleted, normalize_error,
                           mentions_json, raw_json
                    FROM messages
                    WHERE chat_id = ?
                    ORDER BY COALESCE(create_time_ms, 0),
                             COALESCE(message_position, 0),
                             message_id
                    """,
                    (chat_id,),
                )
            ]
            affected = self._purge_chat(conn, chat_id)
            chunks, skipped = build_chunks(rows)
            counts = {
                "messages_scanned": len(rows),
                "messages_indexed": 0,
                "messages_skipped": len(skipped),
                "chunks_created": 0,
                "vectors_created": 0,
                "entities_created": 0,
                "edges_created": 0,
            }
            now = iso_now()
            row_by_id = {str(row["message_id"]): row for row in rows}
            seen_entity_ids: set[str] = set(affected)
            for chunk in chunks:
                message_ids = json.loads(chunk["message_ids_json"])
                content = str(chunk["content"] or "")
                search_text = tokenize_search_text(content)
                tf = token_counts(content)
                cursor = conn.execute(
                    """
                    INSERT INTO chunks (
                        chat_id, thread_id, topic_key, chunk_seq,
                        message_id_start, message_id_end, message_count,
                        message_ids_json, content, search_text, content_hash,
                        start_time_ms, end_time_ms, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        chunk.get("thread_id") or None,
                        chunk["topic_key"],
                        chunk["chunk_seq"],
                        chunk["message_id_start"],
                        chunk["message_id_end"],
                        chunk["message_count"],
                        chunk["message_ids_json"],
                        content,
                        search_text,
                        chunk["content_hash"],
                        chunk.get("start_time_ms"),
                        chunk.get("end_time_ms"),
                        now,
                        now,
                    ),
                )
                chunk_id = int(cursor.lastrowid)
                conn.execute(
                    """
                    INSERT INTO chunk_vectors (chunk_id, total_terms, term_freqs_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        int(sum(tf.values())),
                        json.dumps(tf, ensure_ascii=True, sort_keys=True),
                        now,
                    ),
                )
                counts["chunks_created"] += 1
                counts["vectors_created"] += 1
                counts["messages_indexed"] += chunk["message_count"]
                for line_seq, message_id in enumerate(message_ids, start=1):
                    conn.execute(
                        """
                        INSERT INTO chunk_messages (chunk_id, message_id, line_seq)
                        VALUES (?, ?, ?)
                        """,
                        (chunk_id, message_id, line_seq),
                    )
                    row = row_by_id.get(str(message_id))
                    if row is None:
                        continue
                    result = self._index_message(conn, row, chat_name)
                    counts["entities_created"] += result["new_entities"]
                    counts["edges_created"] += result["edges_created"]
                    seen_entity_ids.update(result["entity_ids"])
            self._refresh_entities(conn, seen_entity_ids)
            conn.commit()
            return counts
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    # 删除一个群关联的 chunk、向量、实体边等派生记录，返回受影响实体。
    def _purge_chat(conn: sqlite3.Connection, chat_id: str) -> set[str]:
        affected = {
            str(row["entity_id"])
            for row in conn.execute(
                "SELECT DISTINCT entity_id FROM entity_mentions WHERE chat_id = ?",
                (chat_id,),
            )
        }
        conn.execute(
            """
            DELETE FROM chunk_vectors
            WHERE chunk_id IN (SELECT id FROM chunks WHERE chat_id = ?)
            """,
            (chat_id,),
        )
        conn.execute(
            """
            DELETE FROM chunk_messages
            WHERE chunk_id IN (SELECT id FROM chunks WHERE chat_id = ?)
            """,
            (chat_id,),
        )
        conn.execute("DELETE FROM chunks WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM edges WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM entity_mentions WHERE chat_id = ?", (chat_id,))
        return affected

    @staticmethod
    # 索引单条消息：抽出实体关系、更新提及并关联到 chunk。
    def _index_message(
        conn: sqlite3.Connection,
        row: dict[str, Any],
        chat_name: str,
    ) -> dict[str, Any]:
        entities = extract_message_entities(
            row,
            chat_name=chat_name,
            chat_id=str(row.get("chat_id") or ""),
        )
        reply_target: dict[str, Any] | None = None
        target_id = reply_to_message_id(row)
        reply_source = str(row.get("sender_name") or "").strip()
        if target_id and reply_source:
            target = conn.execute(
                "SELECT sender_name FROM messages WHERE message_id = ?",
                (target_id,),
            ).fetchone()
            target_name = str(target["sender_name"] or "").strip() if target else ""
            if target_name:
                reply_target = {
                    "entity_id": entity_id("person", target_name),
                    "entity_type": "person",
                    "value": target_name,
                    "canonical": target_name,
                    "occurrence": 1,
                }
                entities.append(reply_target)

        message_id = str(row.get("message_id") or "")
        chat_id = str(row.get("chat_id") or "")
        now = iso_now()
        new_entities = 0
        entity_ids: set[str] = set()
        for entity in entities:
            eid = str(entity["entity_id"] or entity_id(entity["entity_type"], entity["value"]))
            entity_ids.add(eid)
            if IndexRepository._ensure_entity(conn, eid, entity):
                new_entities += 1
            conn.execute(
                """
                INSERT INTO entity_mentions (entity_id, message_id, chat_id, occurrence)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(entity_id, message_id) DO UPDATE SET
                    occurrence = entity_mentions.occurrence + excluded.occurrence
                """,
                (eid, message_id, chat_id, int(entity.get("occurrence") or 1)),
            )

        ordered = sorted(entity_ids)
        evidence = _evidence_text(row)
        edges_created = 0
        for index_i in range(len(ordered)):
            for index_j in range(index_i + 1, len(ordered)):
                source, target = ordered[index_i], ordered[index_j]
                conn.execute(
                    """
                    INSERT INTO edges (
                        source_entity_id, target_entity_id, edge_type,
                        chat_id, message_id, weight, evidence_text,
                        created_at, updated_at
                    ) VALUES (?, ?, 'co_occur', ?, ?, 1, ?, ?, ?)
                    ON CONFLICT(
                        source_entity_id, target_entity_id, edge_type,
                        chat_id, message_id
                    ) DO UPDATE SET
                        weight = excluded.weight,
                        evidence_text = excluded.evidence_text,
                        updated_at = excluded.updated_at
                    """,
                    (source, target, chat_id, message_id, evidence, now, now),
                )
                edges_created += 1

        if reply_target and reply_source:
            source_entity = entity_id("person", reply_source)
            target_entity = str(reply_target["entity_id"])
            if source_entity != target_entity:
                conn.execute(
                    """
                    INSERT INTO edges (
                        source_entity_id, target_entity_id, edge_type,
                        chat_id, message_id, weight, evidence_text,
                        created_at, updated_at
                    ) VALUES (?, ?, 'replied_to', ?, ?, 1, ?, ?, ?)
                    ON CONFLICT(
                        source_entity_id, target_entity_id, edge_type,
                        chat_id, message_id
                    ) DO UPDATE SET
                        weight = excluded.weight,
                        evidence_text = excluded.evidence_text,
                        updated_at = excluded.updated_at
                    """,
                    (
                        source_entity,
                        target_entity,
                        chat_id,
                        message_id,
                        evidence,
                        now,
                        now,
                    ),
                )
                edges_created += 1
        return {
            "new_entities": new_entities,
            "edges_created": edges_created,
            "entity_ids": entity_ids,
        }

    @staticmethod
    # 保证实体存在并返回稳定的 entity_id。
    def _ensure_entity(
        conn: sqlite3.Connection,
        eid: str,
        entity: dict[str, Any],
    ) -> bool:
        exists = conn.execute(
            "SELECT 1 FROM entities WHERE entity_id = ?", (eid,)
        ).fetchone()
        if exists:
            return False
        now = iso_now()
        conn.execute(
            """
            INSERT INTO entities (
                entity_id, entity_type, value, canonical, occurrence,
                first_seen_at_ms, last_seen_at_ms, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?)
            """,
            (
                eid,
                entity["entity_type"],
                entity["value"],
                entity.get("canonical") or entity["value"],
                now,
                now,
            ),
        )
        return True

    @staticmethod
    # 重建实体提及计数并清理不再被引用的孤立实体。
    def _refresh_entities(
        conn: sqlite3.Connection,
        entity_ids: set[str],
    ) -> None:
        now = iso_now()
        for eid in entity_ids:
            total = conn.execute(
                """
                SELECT COALESCE(SUM(occurrence), 0) AS total
                FROM entity_mentions
                WHERE entity_id = ?
                """,
                (eid,),
            ).fetchone()["total"]
            if not total:
                conn.execute(
                    """
                    DELETE FROM edges
                    WHERE source_entity_id = ? OR target_entity_id = ?
                    """,
                    (eid, eid),
                )
                conn.execute("DELETE FROM entities WHERE entity_id = ?", (eid,))
                continue
            agg = conn.execute(
                """
                SELECT COALESCE(MIN(m.create_time_ms), 0) AS first_ms,
                       COALESCE(MAX(m.create_time_ms), 0) AS last_ms
                FROM entity_mentions em
                JOIN messages m ON m.message_id = em.message_id
                WHERE em.entity_id = ?
                """,
                (eid,),
            ).fetchone()
            conn.execute(
                """
                UPDATE entities
                SET occurrence = ?, first_seen_at_ms = ?, last_seen_at_ms = ?,
                    updated_at = ?
                WHERE entity_id = ?
                """,
                (int(total), int(agg["first_ms"]), int(agg["last_ms"]), now, eid),
            )

    # 根据版本游标筛选需要增量索引的群集合。
    def _changed_chat_ids(self, version_cursor: int | None, chat_ids: list[str]) -> set[str]:
        if version_cursor is None:
            return set(str(chat_id) for chat_id in chat_ids)
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT m.chat_id
                FROM messages m
                WHERE m.chat_id IN ({})
                  AND (
                    EXISTS (
                        SELECT 1 FROM message_versions v
                        WHERE v.message_id = m.message_id
                          AND v.id > ?
                    )
                  )
                """.format(", ".join("?" * len(chat_ids))),
                (*chat_ids, version_cursor),
            ).fetchall()
            return {str(row["chat_id"]) for row in rows}
        finally:
            conn.close()

    # 返回当前已有派生索引的群 id 集合。
    def _indexed_chat_ids(self) -> set[str]:
        conn = self._connect()
        try:
            return {
                str(row["chat_id"])
                for row in conn.execute("SELECT DISTINCT chat_id FROM chunks")
            }
        finally:
            conn.close()

    # 清空全部派生索引表，包括 FTS5 虚拟表。
    def _clear_derived(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM chunk_vectors")
            conn.execute("DELETE FROM chunk_messages")
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM edges")
            conn.execute("DELETE FROM entity_mentions")
            conn.execute("DELETE FROM entities")
            conn.commit()
        finally:
            conn.close()

    # 持久化一次索引运行的统计、范围与错误明细。
    def _record_run(
        self,
        *,
        started: datetime,
        mode: str,
        rebuild_id: str,
        scope: dict[str, Any],
        indexed_chat_ids: list[str],
        totals: dict[str, int],
        errors: list[dict[str, str]],
    ) -> int:
        finished = datetime.now().astimezone()
        duration_ms = int((finished - started).total_seconds() * 1000)
        conn = self._connect()
        try:
            version_cursor = int(
                conn.execute(
                    "SELECT COALESCE(MAX(id), 0) FROM message_versions"
                ).fetchone()[0]
            )
            cursor = conn.execute(
                """
                INSERT INTO index_runs (
                    started_at, finished_at, duration_ms, mode, scope,
                    chat_ids_json, rebuild_id, version_cursor, chats_indexed,
                    chats_failed, messages_scanned, messages_indexed,
                    messages_skipped, chunks_created, vectors_created,
                    entities_created, edges_created, errors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started.isoformat(timespec="seconds"),
                    finished.isoformat(timespec="seconds"),
                    duration_ms,
                    mode,
                    json.dumps(scope, ensure_ascii=False, sort_keys=True),
                    json.dumps(indexed_chat_ids, ensure_ascii=False),
                    rebuild_id,
                    version_cursor,
                    int(totals["chats_indexed"]),
                    int(totals["chats_failed"]),
                    int(totals["messages_scanned"]),
                    int(totals["messages_indexed"]),
                    int(totals["messages_skipped"]),
                    int(totals["chunks_created"]),
                    int(totals["vectors_created"]),
                    int(totals["entities_created"]),
                    int(totals["edges_created"]),
                    json.dumps(errors, ensure_ascii=False),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    # 读取最近一次索引运行并反序列化 JSON 字段。
    def _last_run_decoded(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM index_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return self._decode_run(row) if row else None
        finally:
            conn.close()

    @staticmethod
    # 把索引运行行转换为字典并解析 JSON 字段。
    def _decode_run(row: sqlite3.Row) -> dict[str, Any]:
        run = dict(row)
        for key in ("errors_json",):
            try:
                run["errors"] = json.loads(run.pop(key) or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                run["errors"] = []
        for key in ("scope", "chat_ids_json"):
            try:
                run[key] = json.loads(run[key] or "null")
            except (TypeError, ValueError, json.JSONDecodeError):
                run[key] = None
        return run

    @staticmethod
    # 返回本轮索引运行的零值计数结构。
    def _empty_counts() -> dict[str, int]:
        return {
            "chats_indexed": 0,
            "chats_failed": 0,
            "messages_scanned": 0,
            "messages_indexed": 0,
            "messages_skipped": 0,
            "chunks_created": 0,
            "vectors_created": 0,
            "entities_created": 0,
            "edges_created": 0,
        }

    @staticmethod
    # 把单群索引计数合并进本轮总量。
    def _add_counts(
        totals: dict[str, int],
        counts: dict[str, int],
    ) -> None:
        for key in (
            "messages_scanned",
            "messages_indexed",
            "messages_skipped",
            "chunks_created",
            "vectors_created",
            "entities_created",
            "edges_created",
        ):
            totals[key] += int(counts.get(key) or 0)

    # 打开数据库连接并启用行映射与外键约束。
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


    # 从检索结果行提取展示用摘要文本。
def _evidence_text(row: dict[str, Any]) -> str:
    text = str(row.get("content_normalized") or "").strip()
    return text[:MAX_EVIDENCE_CHARS]
