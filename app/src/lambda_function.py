import json
import os
import time
import hashlib
from typing import Dict, List, Tuple

import boto3
import faiss
import numpy as np
import tiktoken
from botocore.exceptions import ClientError
from openai import OpenAI


S3_BUCKET = os.environ["S3_BUCKET"]
RUNBOOK_PREFIX = os.getenv("RUNBOOK_PREFIX", "")
OPENAI_API_KEY_SSM_PARAM = os.environ["OPENAI_API_KEY_SSM_PARAM"]
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-3.5-turbo")
CHUNK_SIZE_TOKENS = int(os.getenv("CHUNK_SIZE_TOKENS", "500"))
CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "50"))
TOP_K = int(os.getenv("TOP_K", "4"))
METRICS_NAMESPACE = os.getenv("METRICS_NAMESPACE", "ServerlessRag")

CACHE_DIR = "/tmp/rag_cache"
INDEX_PATH = f"{CACHE_DIR}/index.faiss"
CHUNKS_PATH = f"{CACHE_DIR}/chunks.json"
MANIFEST_PATH = f"{CACHE_DIR}/manifest.json"

s3_client = boto3.client("s3")
ssm_client = boto3.client("ssm")
cloudwatch_client = boto3.client("cloudwatch")

_openai_client = None
_ssm_api_key_cache = None
_runtime_cache: Dict[str, object] = {
    "manifest_hash": None,
    "index": None,
    "chunks": None,
}


def _build_response(status_code: int, payload: Dict) -> Dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def _get_openai_client() -> OpenAI:
    global _openai_client, _ssm_api_key_cache

    if _openai_client is not None:
        return _openai_client

    if _ssm_api_key_cache is None:
        param = ssm_client.get_parameter(Name=OPENAI_API_KEY_SSM_PARAM, WithDecryption=True)
        _ssm_api_key_cache = param["Parameter"]["Value"]

    _openai_client = OpenAI(api_key=_ssm_api_key_cache)
    return _openai_client


def _list_runbook_objects() -> List[Dict]:
    paginator = s3_client.get_paginator("list_objects_v2")
    page_iter = paginator.paginate(Bucket=S3_BUCKET, Prefix=RUNBOOK_PREFIX)

    objects: List[Dict] = []
    for page in page_iter:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            objects.append({"Key": key, "ETag": obj["ETag"], "Size": obj["Size"]})
    return objects


def _manifest_hash(objects: List[Dict]) -> str:
    normalized = sorted(objects, key=lambda x: x["Key"])
    manifest_str = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(manifest_str.encode("utf-8")).hexdigest()


def _download_text_from_s3(key: str) -> str:
    obj = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
    body = obj["Body"].read()
    return body.decode("utf-8", errors="ignore")


def _get_tokenizer():
    try:
        return tiktoken.encoding_for_model(EMBEDDING_MODEL)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def _chunk_text(text: str, source_key: str) -> List[Dict]:
    tokenizer = _get_tokenizer()
    token_ids = tokenizer.encode(text)

    if CHUNK_OVERLAP_TOKENS >= CHUNK_SIZE_TOKENS:
        raise ValueError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_SIZE_TOKENS")

    chunks: List[Dict] = []
    start = 0
    step = CHUNK_SIZE_TOKENS - CHUNK_OVERLAP_TOKENS
    chunk_id = 0

    while start < len(token_ids):
        end = min(start + CHUNK_SIZE_TOKENS, len(token_ids))
        chunk_tokens = token_ids[start:end]
        chunk_text = tokenizer.decode(chunk_tokens)
        chunks.append(
            {
                "source": source_key,
                "chunk_id": chunk_id,
                "text": chunk_text,
            }
        )
        if end == len(token_ids):
            break
        start += step
        chunk_id += 1

    return chunks


def _build_chunks_from_s3(objects: List[Dict]) -> List[Dict]:
    all_chunks: List[Dict] = []
    for obj in objects:
        text = _download_text_from_s3(obj["Key"])
        if not text.strip():
            continue
        all_chunks.extend(_chunk_text(text, obj["Key"]))
    return all_chunks


def _embed_texts(texts: List[str]) -> np.ndarray:
    client = _get_openai_client()
    vectors: List[List[float]] = []

    # Batching keeps request counts lower and avoids payload limits in a single embeddings call.
    batch_size = 64
    for idx in range(0, len(texts), batch_size):
        batch = texts[idx : idx + batch_size]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        vectors.extend(item.embedding for item in response.data)

    return np.array(vectors, dtype=np.float32)


def _persist_cache(index: faiss.Index, chunks: List[Dict], manifest_hash: str) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    faiss.write_index(index, INDEX_PATH)

    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        json.dump(chunks, f)

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump({"manifest_hash": manifest_hash}, f)


def _load_cache_from_disk() -> Tuple[faiss.Index, List[Dict], str]:
    if not (os.path.exists(INDEX_PATH) and os.path.exists(CHUNKS_PATH) and os.path.exists(MANIFEST_PATH)):
        raise FileNotFoundError("Cache files not present")

    index = faiss.read_index(INDEX_PATH)

    with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    return index, chunks, manifest["manifest_hash"]


def _ensure_index() -> Tuple[faiss.Index, List[Dict]]:
    objects = _list_runbook_objects()
    if not objects:
        raise ValueError("No runbooks found in S3 bucket/prefix")

    current_manifest_hash = _manifest_hash(objects)

    if _runtime_cache["manifest_hash"] == current_manifest_hash:
        return _runtime_cache["index"], _runtime_cache["chunks"]

    try:
        disk_index, disk_chunks, disk_manifest_hash = _load_cache_from_disk()
        if disk_manifest_hash == current_manifest_hash:
            _runtime_cache["index"] = disk_index
            _runtime_cache["chunks"] = disk_chunks
            _runtime_cache["manifest_hash"] = disk_manifest_hash
            return disk_index, disk_chunks
    except (FileNotFoundError, KeyError, ValueError):
        pass

    chunks = _build_chunks_from_s3(objects)
    if not chunks:
        raise ValueError("Runbooks were found but no readable text chunks were created")

    vectors = _embed_texts([chunk["text"] for chunk in chunks])
    index = faiss.IndexFlatL2(vectors.shape[1])
    index.add(vectors)

    _persist_cache(index, chunks, current_manifest_hash)

    _runtime_cache["index"] = index
    _runtime_cache["chunks"] = chunks
    _runtime_cache["manifest_hash"] = current_manifest_hash

    return index, chunks


def _retrieve(question: str, index: faiss.Index, chunks: List[Dict]) -> List[Dict]:
    query_vec = _embed_texts([question])

    # TODO: If query volume grows, replace FAISS-on-Lambda with a managed vector DB.
    # Tradeoff: managed stores add operational cost/network hops, but remove reindexing
    # pressure and provide durable, shared indexes across concurrent Lambda instances.
    distances, indices = index.search(query_vec, TOP_K)

    results: List[Dict] = []
    for i, idx in enumerate(indices[0]):
        if idx < 0 or idx >= len(chunks):
            continue
        item = dict(chunks[idx])
        item["distance"] = float(distances[0][i])
        results.append(item)
    return results


def _build_messages(question: str, retrieved_chunks: List[Dict]) -> List[Dict]:
    context_blocks = []
    for rank, chunk in enumerate(retrieved_chunks, start=1):
        context_blocks.append(
            f"[{rank}] source={chunk['source']}\n{chunk['text']}"
        )

    system_prompt = (
        "You answer infrastructure questions using only the provided runbook context. "
        "If the context is insufficient, say you do not know. "
        "Always include source citations like [source: path/to/file.md]."
    )
    user_prompt = (
        f"Question:\n{question}\n\n"
        f"Runbook context:\n\n{chr(10).join(context_blocks)}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _answer_question(question: str, retrieved_chunks: List[Dict]) -> Tuple[str, int]:
    client = _get_openai_client()
    messages = _build_messages(question, retrieved_chunks)

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        temperature=0.1,
        messages=messages,
    )

    answer = response.choices[0].message.content or "I do not know based on the provided runbooks."
    token_count = int(response.usage.total_tokens) if response.usage else 0
    return answer, token_count


def _emit_metrics(latency_ms: float, token_count: int) -> None:
    # Emit these as custom metrics so query cost and latency trends can be tracked in one namespace.
    cloudwatch_client.put_metric_data(
        Namespace=METRICS_NAMESPACE,
        MetricData=[
            {
                "MetricName": "QueryLatencyMs",
                "Unit": "Milliseconds",
                "Value": latency_ms,
            },
            {
                "MetricName": "OpenAITokenCount",
                "Unit": "Count",
                "Value": token_count,
            },
        ],
    )


def lambda_handler(event, _context):
    start_time = time.perf_counter()
    token_count = 0

    try:
        body = json.loads(event.get("body") or "{}")
        question = (body.get("question") or "").strip()
        if not question:
            return _build_response(400, {"error": "Request body must include a non-empty 'question'"})

        index, chunks = _ensure_index()
        retrieved = _retrieve(question, index, chunks)
        answer, token_count = _answer_question(question, retrieved)

        citations = sorted({item["source"] for item in retrieved})
        return _build_response(
            200,
            {
                "answer": answer,
                "citations": citations,
                "retrieved_chunks": [
                    {
                        "source": item["source"],
                        "chunk_id": item["chunk_id"],
                        "distance": item["distance"],
                    }
                    for item in retrieved
                ],
            },
        )
    except ValueError as exc:
        return _build_response(400, {"error": str(exc)})
    except ClientError as exc:
        return _build_response(502, {"error": f"AWS API error: {str(exc)}"})
    except Exception as exc:
        return _build_response(500, {"error": f"Unhandled error: {str(exc)}"})
    finally:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        try:
            _emit_metrics(elapsed_ms, token_count)
        except Exception:
            # Metrics should never block serving a response.
            pass
