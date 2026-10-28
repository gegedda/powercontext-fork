"""向量化：三档可切换，全部可离线运行。

1. ``onnx``  —— 本地 bge-small-zh-v1.5（onnxruntime + tokenizers），中文语义检索首选；
2. ``hash``  —— 字符 n-gram 特征哈希 + TF-IDF 权重，不需要任何模型文件（默认兜底）；
3. ``api``   —— 任意 OpenAI 兼容 embedding 接口（可选）。

对外只暴露 :class:`Embedder`：``encode_documents`` / ``encode_query`` / ``describe``。
所有向量都做 L2 归一化，保证余弦相似度=内积。
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import numpy as np

# bge 中文模型官方建议的查询前缀；文档侧不加前缀
BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class HashEmbedder:
    """字符 n-gram 特征哈希（hashing trick）+ 子线性 TF。

    没有模型文件也能得到可用的向量；与全文检索融合后足以支撑演示与离线评测。
    """

    name = "hash-char-ngram"

    def __init__(self, dim: int = 512) -> None:
        self.dim = int(dim)

    def _ngrams(self, text: str) -> dict[str, float]:
        text = (text or "").lower()
        tokens = _TOKEN_RE.findall(text)
        grams: dict[str, float] = {}
        for tok in tokens:
            grams[tok] = grams.get(tok, 0.0) + 1.0
            if len(tok) >= 2:
                for i in range(len(tok) - 1):
                    gram = tok[i : i + 2]
                    grams[gram] = grams.get(gram, 0.0) + 0.6
        # 中文按字，相邻两字也是 n-gram；这里 tokens 已按单字切分，再补相邻字组合
        han = [t for t in tokens if len(t) == 1 and "\u4e00" <= t <= "\u9fff"]
        for a, b in zip(han, han[1:]):
            bigram = a + b
            grams[bigram] = grams.get(bigram, 0.0) + 1.0
        return grams

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        grams = self._ngrams(text)
        if not grams:
            return vec
        for gram, count in grams.items():
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign * (1.0 + math.log(count))
        return vec

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return _l2_normalize(np.stack([self._vector(t) for t in texts]))

    def encode_query(self, text: str) -> np.ndarray:
        return _l2_normalize(self._vector(text))

    def describe(self) -> dict:
        return {"provider": self.name, "dim": self.dim, "model": "hashing-char-ngram-tf"}


class OnnxBgeEmbedder:
    """本地 ONNX 版 bge-small-zh-v1.5（CLS pooling + L2 归一化）。"""

    name = "onnx-bge-small-zh-v1.5"

    def __init__(self, model_dir: Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.model_dir = Path(model_dir)
        onnx_files = sorted(self.model_dir.glob("*.onnx"))
        if not onnx_files:
            raise FileNotFoundError(f"{self.model_dir} 下没有 .onnx 模型文件")
        tokenizer_file = self.model_dir / "tokenizer.json"
        if not tokenizer_file.is_file():
            raise FileNotFoundError(f"{tokenizer_file} 不存在")
        self._session = ort.InferenceSession(str(onnx_files[0]), providers=["CPUExecutionProvider"])
        self._tokenizer = Tokenizer.from_file(str(tokenizer_file))
        self._tokenizer.enable_truncation(max_length=512)
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._output_name = self._session.get_outputs()[0].name
        self.dim = int(self._session.get_outputs()[0].shape[-1])

    def _run(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            encoding = self._tokenizer.encode(text or " ")
            ids = np.array([encoding.ids], dtype=np.int64)
            attention = np.array([encoding.attention_mask], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": attention}
            if "token_type_ids" in self._input_names:
                feeds["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run([self._output_name], feeds)[0]
            cls = hidden[0, 0, :]  # bge 使用 [CLS] 表示
            vectors.append(cls.astype(np.float32))
        return _l2_normalize(np.stack(vectors))

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._run(texts)

    def encode_query(self, text: str) -> np.ndarray:
        return self._run([BGE_QUERY_PREFIX + (text or "")])

    def describe(self) -> dict:
        return {
            "provider": self.name,
            "dim": self.dim,
            "model": self.model_dir.name,
            "runtime": "onnxruntime",
        }


class ApiEmbedder:
    """OpenAI 兼容接口（DashScope / DeepSeek / 自建网关等）。"""

    name = "api-openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str, dim: int) -> None:
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key or "EMPTY")
        self.model = model
        self.dim = dim

    def _embed(self, texts: list[str]) -> np.ndarray:
        response = self._client.embeddings.create(model=self.model, input=texts)
        return _l2_normalize(np.array([item.embedding for item in response.data], dtype=np.float32))

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 16):
            out.append(self._embed(texts[i : i + 16]))
        return np.concatenate(out, axis=0) if out else np.zeros((0, self.dim), dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        return self._embed([text])

    def describe(self) -> dict:
        return {"provider": self.name, "dim": self.dim, "model": self.model}


def build_embedder(settings) -> tuple[object, dict]:
    """按配置挑选向量化后端，返回（embedder, 描述信息）。"""

    requested = settings.embedder
    candidates: list[str] = []
    if requested == "auto":
        candidates = ["onnx", "hash"]
    elif requested in {"onnx", "hash", "api"}:
        candidates = [requested]
    else:
        candidates = ["hash"]

    notes: list[str] = []
    for candidate in candidates:
        try:
            if candidate == "onnx":
                embedder = OnnxBgeEmbedder(settings.embed_model_dir)
                info = embedder.describe()
                info["fallback_notes"] = notes
                return embedder, info
            if candidate == "api":
                if not (settings.embed_api_base and settings.embed_api_key):
                    raise RuntimeError("缺少 WENGU_EMBED_API_BASE / WENGU_EMBED_API_KEY")
                embedder = ApiEmbedder(
                    settings.embed_api_base,
                    settings.embed_api_key,
                    settings.embed_api_model,
                    settings.embed_dim,
                )
                info = embedder.describe()
                info["fallback_notes"] = notes
                return embedder, info
            if candidate == "hash":
                embedder = HashEmbedder(settings.embed_dim)
                info = embedder.describe()
                info["fallback_notes"] = notes
                return embedder, info
        except Exception as exc:  # noqa: BLE001 - 逐级降级是有意设计
            notes.append(f"{candidate} 不可用：{exc}")
            continue
    embedder = HashEmbedder(settings.embed_dim)
    info = embedder.describe()
    info["fallback_notes"] = notes
    return embedder, info
