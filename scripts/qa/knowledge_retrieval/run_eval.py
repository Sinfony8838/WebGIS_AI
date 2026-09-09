"""知识库中文检索评测：基线( main 现有逻辑 ) vs 优化后检索引擎。

用法（仓库根目录）：
  python scripts/qa/knowledge_retrieval/run_eval.py --split all
  python scripts/qa/knowledge_retrieval/run_eval.py --split tune    # 调参用
  python scripts/qa/knowledge_retrieval/run_eval.py --split heldout # 保留测试集

评测对象是真实服务代码路径：语料写入临时 knowledge_dir 后实例化
KnowledgeBaseService / KnowledgeService。基线为逐行复刻 main 起始提交
（00bb920）中 KnowledgeBaseService.search 的打分逻辑，便于对照。

指标：Recall@5、Hit@1、MRR、nDCG@5、无答案误命中率、p50/p95 延迟、
权限隔离（跨用户泄漏必须为 0）、更新/删除后的失效检查。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import AppConfig  # noqa: E402
from backend.app.services.knowledge import KnowledgeService  # noqa: E402
from backend.app.services.knowledge_base import KnowledgeBaseService  # noqa: E402
from scripts.qa.knowledge_retrieval.samples import load_samples  # noqa: E402

CORPUS_PATH = Path(__file__).resolve().parent / "corpus.json"
REPORT_JSON = Path(__file__).resolve().parent / "report.json"

TOP_K = 5
NO_ANSWER_TOP_K = 5


# --------------------------------------------------------------------------
# 基线：复刻 main 起始提交 00bb920 的 KnowledgeBaseService.search 打分逻辑
# --------------------------------------------------------------------------
def _baseline_normalize_keywords(value: Any) -> list[str]:
    raw: list[str] = []
    if isinstance(value, str):
        raw = [part.strip() for part in re.split(r"[;,，\s]+", value) if part.strip()]
    elif isinstance(value, list):
        raw = [str(item or "").strip() for item in value if str(item or "").strip()]
    seen = set()
    out = []
    for item in raw:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(item)
    return out


def baseline_search(items: list[dict], query: str, limit: int = TOP_K) -> list[dict]:
    query_tokens = [token for token in _baseline_normalize_keywords(query) if token]
    rows: list[tuple[int, str, dict]] = []
    for item in items:
        keywords = _baseline_normalize_keywords(item.get("keywords"))
        tags = _baseline_normalize_keywords(item.get("tags")) or keywords
        haystack_parts = [
            str(item.get("title") or ""),
            str(item.get("topic") or ""),
            str(item.get("region") or ""),
            str(item.get("summary") or ""),
            str(item.get("canonical_answer") or ""),
            " ".join(keywords),
            " ".join(tags),
        ]
        haystack = " ".join(part.lower() for part in haystack_parts if part)
        score = 0
        if query_tokens:
            token_hits = sum(1 for token in query_tokens if token.lower() in haystack)
            if token_hits == 0:
                continue
            score += token_hits
        rows.append((score, str(item.get("updated_at") or ""), item))
    rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item for _, _, item in rows[:limit]]


# --------------------------------------------------------------------------
# 语料与被测服务
# --------------------------------------------------------------------------
def build_corpus_items() -> list[dict]:
    """内置清单 + geo 单元（转为清单形态）+ 评测合成资料。"""
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(
        (REPO_ROOT / corpus["builtin_manifest"]).read_text(encoding="utf-8")
    )
    items = [item for item in manifest.get("items", []) if isinstance(item, dict)]
    geo = json.loads((REPO_ROOT / corpus["builtin_geo"]).read_text(encoding="utf-8"))
    for unit in geo:
        items.append(
            {
                "id": unit.get("id"),
                "title": unit.get("title"),
                "topic": unit.get("domain") or "geo_concept",
                "region": "",
                "time": "",
                "source": "builtin_geo_knowledge",
                "keywords": unit.get("tags") or [],
                "summary": unit.get("canonical_answer") or "",
                "canonical_answer": unit.get("canonical_answer") or "",
                "teaching_points": unit.get("teaching_points") or [],
                "citations": unit.get("citations") or [],
            }
        )
    items.extend(corpus["fixtures"])
    return items


def write_eval_kb(items: list[dict], knowledge_dir: Path) -> None:
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    payload = {"version": "1.0", "updated_at": "2026-09-08T00:00:00+00:00", "items": items}
    (knowledge_dir / "kb_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_kb_service(items: list[dict], root: Path) -> KnowledgeBaseService:
    config = AppConfig()
    knowledge_dir = root / "knowledge"
    write_eval_kb(items, knowledge_dir)
    config.knowledge_dir = knowledge_dir
    return KnowledgeBaseService(config)


def build_card_service(items: list[dict], root: Path) -> KnowledgeService:
    """KnowledgeService 读 config.builtin_dir/knowledge/kb_manifest.json。"""
    from types import SimpleNamespace

    builtin_dir = root / "builtin"
    write_eval_kb(items, builtin_dir / "knowledge")
    return KnowledgeService(SimpleNamespace(builtin_dir=builtin_dir))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# 指标
# --------------------------------------------------------------------------
def rank_metrics(expected: list[str], got: list[str]) -> dict[str, float]:
    if not expected:
        return {}
    top5 = got[:TOP_K]
    recall = len(set(expected) & set(top5)) / len(expected)
    hit1 = 1.0 if got and got[0] in expected else 0.0
    mrr = 0.0
    for index, doc_id in enumerate(got[:TOP_K]):
        if doc_id in expected:
            mrr = 1.0 / (index + 1)
            break
    ideal = sum(1.0 / math.log2(rank + 2) for rank in range(min(len(expected), TOP_K)))
    dcg = sum(
        1.0 / math.log2(rank + 2)
        for rank, doc_id in enumerate(top5)
        if doc_id in expected
    )
    ndcg = dcg / ideal if ideal else 0.0
    return {"recall5": recall, "hit1": hit1, "mrr": mrr, "ndcg5": ndcg}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_split(samples: list[dict], searcher, top_k: int = TOP_K) -> dict[str, Any]:
    per_category: dict[str, dict[str, list[float]]] = {}
    latencies: list[float] = []
    rows: list[dict] = []
    no_answer_total = 0
    no_answer_false_hit = 0
    for sample in samples:
        expected = sample["expected"]
        started = time.perf_counter()
        got_ids = searcher(sample["query"])[:top_k]
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies.append(elapsed_ms)
        category = sample["category"]
        bucket = per_category.setdefault(
            category, {"recall5": [], "hit1": [], "mrr": [], "ndcg5": []}
        )
        if category == "no_answer":
            no_answer_total += 1
            if got_ids:
                no_answer_false_hit += 1
            rows.append({**sample, "got": got_ids, "false_hit": bool(got_ids)})
            continue
        metrics = rank_metrics(expected, got_ids)
        for key, value in metrics.items():
            bucket[key].append(value)
        rows.append({**sample, "got": got_ids, **metrics})

    summary: dict[str, Any] = {
        "samples": len(samples),
        "recall5": round(
            _mean([value for bucket in per_category.values() for value in bucket["recall5"]]), 4
        ),
        "hit1": round(
            _mean([value for bucket in per_category.values() for value in bucket["hit1"]]), 4
        ),
        "mrr": round(
            _mean([value for bucket in per_category.values() for value in bucket["mrr"]]), 4
        ),
        "ndcg5": round(
            _mean([value for bucket in per_category.values() for value in bucket["ndcg5"]]), 4
        ),
        "no_answer_total": no_answer_total,
        "no_answer_false_hit": no_answer_false_hit,
        "no_answer_false_hit_rate": round(
            no_answer_false_hit / no_answer_total if no_answer_total else 0.0, 4
        ),
        "latency_p50_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
        "latency_p95_ms": round(
            sorted(latencies)[int(0.95 * (len(latencies) - 1))], 2
        )
        if latencies
        else 0.0,
        "categories": {},
    }
    for category, bucket in per_category.items():
        summary["categories"][category] = {
            "samples": len(bucket["recall5"]),
            "recall5": round(_mean(bucket["recall5"]), 4),
            "hit1": round(_mean(bucket["hit1"]), 4),
            "mrr": round(_mean(bucket["mrr"]), 4),
            "ndcg5": round(_mean(bucket["ndcg5"]), 4),
        }
    return {"summary": summary, "rows": rows}


def permission_and_freshness_checks(items: list[dict], root: Path) -> dict[str, Any]:
    """权限隔离 + 新增/更新/删除后的立即生效检查。"""
    config = AppConfig()
    knowledge_dir = root / "perm_knowledge"
    write_eval_kb(items, knowledge_dir)
    config.knowledge_dir = knowledge_dir
    service = KnowledgeBaseService(config)
    results: dict[str, Any] = {}

    # 两个用户各自建同名私有资料，内容不同。
    service.upsert_item(
        {
            "id": "private_a",
            "title": "私有教学案例",
            "topic": "private_case",
            "region": "china",
            "keywords": ["私有案例", "教学"],
            "summary": "用户A专属的私有案例内容。",  # A 侧内容
            "owner_user_id": "user_a",
        },
        owner_user_id="user_a",
    )
    service.upsert_item(
        {
            "id": "private_b",
            "title": "私有教学案例",
            "topic": "private_case",
            "region": "china",
            "keywords": ["私有案例", "教学"],
            "summary": "用户B专属的私有案例内容。",  # B 侧内容
            "owner_user_id": "user_b",
        },
        owner_user_id="user_b",
    )

    query_a = service.search("私有教学案例", owner_user_id="user_a")
    ids_a = [item["id"] for item in query_a["items"]]
    query_b = service.search("私有教学案例", owner_user_id="user_b")
    ids_b = [item["id"] for item in query_b["items"]]
    leak = (
        "private_b" in ids_a
        or "private_a" in ids_b
        or any(item["summary"].startswith("用户B") for item in query_a["items"])
        or any(item["summary"].startswith("用户A") for item in query_b["items"])
    )
    # 跨用户缓存复用：A 已填充结果缓存后，B 用相同问句查询（上面顺序已保证），
    # 再次交替查询确认缓存键隔离。
    again_a = [item["id"] for item in service.search("私有教学案例", owner_user_id="user_a")["items"]]
    leak = leak or "private_b" in again_a
    results["cross_user_leak"] = bool(leak)
    results["cross_user_leak_count"] = int(leak)
    # 管理员可见性用 manifest 检查：搜索结果会按设计对同题条目判重，
    # 权限层面的可见性以清单为准。
    manifest_admin = service.get_manifest(owner_user_id="admin", include_all=True)
    admin_ids = {item["id"] for item in manifest_admin["items"]}
    results["admin_sees_both"] = {"private_a", "private_b"} <= admin_ids
    manifest_b = service.get_manifest(owner_user_id="user_b")
    results["private_manifest_isolated"] = "private_a" not in {
        item["id"] for item in manifest_b["items"]
    }

    # 新增 → 立即可搜；更新 → 立即反映；删除 → 立即消失。
    service.upsert_item(
        {
            "id": "fresh_item",
            "title": "长三角城市群专题资料",
            "topic": "urbanization",
            "region": "china",
            "keywords": ["长三角", "城市群"],
            "summary": "长三角城市群的课堂专题资料。",
            "owner_user_id": "user_a",
        },
        owner_user_id="user_a",
    )
    added_visible = any(
        item["id"] == "fresh_item"
        for item in service.search("长三角城市群", owner_user_id="user_a")["items"]
    )
    service.upsert_item(
        {
            "id": "fresh_item",
            "title": "长三角城市群专题资料",
            "topic": "urbanization",
            "region": "china",
            "keywords": ["长三角", "城市群", "更新后关键词成渝"],
            "summary": "更新后的摘要：补充成渝城市群的对比视角。",
            "owner_user_id": "user_a",
        },
        owner_user_id="user_a",
    )
    updated = service.search("成渝城市群", owner_user_id="user_a")
    updated_visible = any(
        item["id"] == "fresh_item" for item in updated["items"]
    )
    service.delete_item("fresh_item", owner_user_id="user_a")
    deleted_gone = not any(
        item["id"] == "fresh_item"
        for item in service.search("长三角城市群", owner_user_id="user_a")["items"]
    )
    builtin_delete_rejected = False
    try:
        service.delete_item(items[0]["id"], owner_user_id="user_a")
    except ValueError:
        builtin_delete_rejected = True
    results.update(
        {
            "add_visible_immediately": bool(added_visible),
            "update_visible_immediately": bool(updated_visible),
            "delete_gone_immediately": bool(deleted_gone),
            "builtin_delete_rejected": builtin_delete_rejected,
        }
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["tune", "heldout", "all"], default="all")
    parser.add_argument("--dump-rows", action="store_true", help="在报告中保留逐样本结果")
    args = parser.parse_args()

    samples = load_samples()
    if args.split != "all":
        samples = [sample for sample in samples if sample["split"] == args.split]

    items = build_corpus_items()
    with tempfile.TemporaryDirectory(prefix="kb_eval_") as tmp:
        root = Path(tmp)
        kb_service = build_kb_service(items, root)
        card_service = build_card_service(items, root)

        def candidate_search(query: str) -> list[str]:
            payload = kb_service.search(query=query, limit=TOP_K)
            return [str(item.get("id")) for item in payload.get("items", [])]

        def baseline_searcher(query: str) -> list[str]:
            return [
                str(item.get("id"))
                for item in baseline_search(items, query, limit=TOP_K)
            ]

        def card_searcher(query: str) -> list[str]:
            return [str(card.get("id")) for card in card_service.search(query, limit=3)]

        index_start = time.perf_counter()
        kb_service.search("人口", limit=1)  # 触发索引构建
        index_build_ms = (time.perf_counter() - index_start) * 1000.0

        candidate = evaluate_split(samples, candidate_search)
        baseline = evaluate_split(samples, baseline_searcher)
        cards = evaluate_split(
            [sample for sample in samples if sample["category"] != "no_answer"],
            card_searcher,
            top_k=3,
        )
        cards_no_answer = evaluate_split(
            [sample for sample in samples if sample["category"] == "no_answer"],
            card_searcher,
            top_k=3,
        )
        permission = permission_and_freshness_checks(items, root)

    report = {
        "corpus_size": len(items),
        "index_build_ms": round(index_build_ms, 2),
        "candidate": candidate["summary"],
        "baseline": baseline["summary"],
        "cards_knowledge_service": {
            **cards["summary"],
            "no_answer_false_hit_rate": cards_no_answer["summary"]["no_answer_false_hit_rate"],
            "no_answer_total": cards_no_answer["summary"]["no_answer_total"],
        },
        "permission_and_freshness": permission,
        "rows": {"candidate": candidate["rows"], "baseline": baseline["rows"]}
        if args.dump_rows
        else {},
    }
    REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
