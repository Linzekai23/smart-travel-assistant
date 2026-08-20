"""下载 BGE 模型（ModelScope）。用法：python -m app.rag.download_model

huggingface.co 在中国大陆不可达，模型必须从 ModelScope 拉取到本地目录，
之后加载走本地路径（离线）。已存在时跳过（可重试）。
"""
import os
import sys
from pathlib import Path

from app.rag.embeddings import MODEL_ID


def default_model_dir() -> Path:
    return Path(os.environ.get("RAG_MODEL_DIR", Path(__file__).resolve().parents[2] / "data" / "bge-model"))


def ensure_model(model_dir: str | Path) -> str:
    """下载（若不存在）并返回本地模型路径。"""
    model_dir = Path(model_dir)
    if model_dir.exists() and any(model_dir.iterdir()):
        return str(model_dir)
    from modelscope import snapshot_download

    model_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(MODEL_ID, local_dir=str(model_dir))
    return str(model_dir)


def main() -> None:
    model_dir = default_model_dir()
    path = ensure_model(model_dir)
    print(f"BGE 模型就绪: {path}")


if __name__ == "__main__":
    sys.exit(main())
