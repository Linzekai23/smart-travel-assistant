"""BGE 中文 embedding 封装。

- 模型：BAAI/bge-small-zh-v1.5（512 维，约 95MB，CPU 推理）
- 下载：ModelScope（huggingface.co 在中国大陆不可达），见 download_model.py
- 池化：BGE 官方要求 [CLS] token 池化 + L2 归一化
- 检索指令：query 侧必须加前缀"为这个句子生成表示以用于检索相关文章："，
  document 侧不加 —— 这是 bge 检索质量的关键细节

测试不加载真实模型（FakeEmbedder 替代）；真实加载只在
python -m app.rag.download_model + ingest 冒烟时发生。
"""
from __future__ import annotations

from transformers import AutoModel, AutoTokenizer

MODEL_ID = "BAAI/bge-small-zh-v1.5"

# BGE 官方查询指令（仅 query 侧使用）
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class Embedder:
    def __init__(self, model_path: str) -> None:
        """model_path 为 ModelScope 下载后的本地目录。"""
        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = AutoModel.from_pretrained(model_path)
        self._model.eval()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """文档侧编码（不加指令），返回 L2 归一化向量列表。"""
        return self._encode(texts, with_instruction=False)

    def embed_query(self, text: str) -> list[float]:
        """查询侧编码（加指令前缀）。"""
        return self._encode([text], with_instruction=True)[0]

    def _encode(self, texts: list[str], *, with_instruction: bool) -> list[list[float]]:
        import torch

        if with_instruction:
            texts = [QUERY_INSTRUCTION + t for t in texts]
        inputs = self._tokenizer(
            texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
        )
        with torch.no_grad():
            outputs = self._model(**inputs)
        # CLS token 池化
        cls_vectors = outputs.last_hidden_state[:, 0, :]
        # L2 归一化
        normed = torch.nn.functional.normalize(cls_vectors, p=2, dim=1)
        return normed.tolist()
