"""
finetune/finetune_embeddings.py — Fine-tune BGE-M3 on Kenyan legal citation pairs

Trains BAAI/bge-m3 (or any sentence-transformer model) on the citation pairs
exported by export_pairs.py using MultipleNegativesRankingLoss.

The fine-tuned model is saved to finetune/bge-m3-kenya-legal/ and can be used
immediately by setting:
  EMBEDDING_BACKEND=local
  HF_EMBEDDING_MODEL=finetune/bge-m3-kenya-legal

in your .env file.

WHY THIS WORKS:
  BGE-M3 is a general-purpose multilingual model. It has never seen Kenyan
  statute text or eKLR citations. Fine-tuning with MNRL on citation pairs
  (case summary ↔ cited section) teaches the model that these belong together
  semantically — dramatically improving retrieval recall for legal queries.

  Expected improvement: +15–30% recall@5 on legal queries based on similar
  domain-adaptation experiments on legal corpora.

REQUIREMENTS:
  pip install sentence-transformers datasets

USAGE (local GPU or Colab):
  # 1. Export pairs from Neo4j
  python finetune/export_pairs.py --output finetune/training_pairs.jsonl

  # 2. Fine-tune
  python finetune/finetune_embeddings.py \
      --pairs finetune/training_pairs.jsonl \
      --output finetune/bge-m3-kenya-legal \
      --epochs 3 \
      --batch-size 16

  # 3. Update .env
  EMBEDDING_BACKEND=local
  HF_EMBEDDING_MODEL=finetune/bge-m3-kenya-legal

COLAB NOTE:
  On T4 with batch_size=16, 3000 pairs, 3 epochs ≈ 20 minutes.
  On A100 use batch_size=64 for ~5 minutes.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_pairs(jsonl_path: str) -> tuple[list[str], list[str], list[str]]:
    """Load training pairs. Returns (queries, positives, negatives)."""
    queries, positives, negatives = [], [], []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            q = row.get("query", "").strip()
            p = row.get("positive", "").strip()
            n = row.get("negative", "").strip()
            if q and p:
                queries.append(q)
                positives.append(p)
                negatives.append(n)
    logger.info("Loaded %d training pairs (%d with hard negatives)",
                len(queries), sum(1 for n in negatives if n))
    return queries, positives, negatives


def build_dataset(queries, positives, negatives):
    """Build InputExample list for sentence-transformers."""
    try:
        from sentence_transformers import InputExample
    except ImportError:
        raise ImportError("Run: pip install sentence-transformers")

    examples = []
    for q, p, n in zip(queries, positives, negatives):
        if n:
            # Triplet: (anchor, positive, negative)
            examples.append(InputExample(texts=[q, p, n]))
        else:
            # Pair: (anchor, positive) — MNRL uses in-batch negatives
            examples.append(InputExample(texts=[q, p]))
    return examples


def train(
    pairs_path: str,
    output_path: str,
    base_model: str = "BAAI/bge-m3",
    epochs: int = 3,
    batch_size: int = 16,
    warmup_ratio: float = 0.1,
    eval_split: float = 0.05,
):
    try:
        from sentence_transformers import SentenceTransformer, losses
        from torch.utils.data import DataLoader
        import torch
    except ImportError:
        raise ImportError("Run: pip install sentence-transformers torch")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Device: %s", device)
    if device == "cpu":
        logger.warning(
            "Training on CPU will be very slow. "
            "Use Google Colab (T4/A100) or a machine with a GPU."
        )

    # Load pairs
    queries, positives, negatives = load_pairs(pairs_path)

    # Train / eval split
    n_eval  = max(1, int(len(queries) * eval_split))
    n_train = len(queries) - n_eval

    train_examples = build_dataset(queries[:n_train], positives[:n_train], negatives[:n_train])
    eval_examples  = build_dataset(queries[n_train:], positives[n_train:], negatives[n_train:])

    logger.info("Train: %d  Eval: %d", len(train_examples), len(eval_examples))

    # Load base model
    logger.info("Loading base model '%s'…", base_model)
    model = SentenceTransformer(base_model, device=device)

    # DataLoader
    train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=batch_size)

    # Loss: MultipleNegativesRankingLoss
    # Uses all other positives in the batch as negatives — efficient and effective
    train_loss = losses.MultipleNegativesRankingLoss(model)

    # Warmup steps
    total_steps = len(train_dataloader) * epochs
    warmup_steps = int(total_steps * warmup_ratio)
    logger.info("Total steps: %d  Warmup: %d  Epochs: %d", total_steps, warmup_steps, epochs)

    output_dir = str(Path(output_path))

    # Train
    logger.info("Starting fine-tuning…")
    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=epochs,
        warmup_steps=warmup_steps,
        output_path=output_dir,
        save_best_model=True,
        show_progress_bar=True,
        checkpoint_path=str(Path(output_dir) / "checkpoints"),
        checkpoint_save_steps=max(100, len(train_dataloader)),
    )

    logger.info("Fine-tuning complete. Model saved to: %s", output_dir)

    # Quick sanity check
    logger.info("Running sanity check…")
    test_query = "director voting conflict of interest companies act"
    test_pos   = positives[0] if positives else "section 142 companies act director interest"
    vecs = model.encode([test_query, test_pos], normalize_embeddings=True)
    sim  = float((vecs[0] * vecs[1]).sum())
    logger.info("Similarity (query ↔ positive sample): %.4f  (should be > 0.5)", sim)

    logger.info(
        "\n✓ Done. To use the fine-tuned model:\n"
        "  1. Set in .env:\n"
        "       EMBEDDING_BACKEND=local\n"
        "       HF_EMBEDDING_MODEL=%s\n"
        "  2. Re-run: python setup_vector_index.py\n"
        "     (this re-embeds all nodes with the fine-tuned model)\n"
        "  3. Restart the API: uvicorn main:app --reload",
        output_dir,
    )


def main():
    parser = argparse.ArgumentParser(description="Fine-tune BGE-M3 on Kenyan legal citation pairs")
    parser.add_argument("--pairs",      default="finetune/training_pairs.jsonl",
                        help="Path to training pairs JSONL")
    parser.add_argument("--output",     default="finetune/bge-m3-kenya-legal",
                        help="Output directory for fine-tuned model")
    parser.add_argument("--base-model", default="BAAI/bge-m3",
                        help="Base sentence-transformer model to fine-tune")
    parser.add_argument("--epochs",     type=int,   default=3)
    parser.add_argument("--batch-size", type=int,   default=16,
                        help="Batch size (use 64 on A100, 16 on T4, 4-8 on CPU)")
    parser.add_argument("--warmup",     type=float, default=0.1,
                        help="Warmup ratio (fraction of total steps)")
    args = parser.parse_args()

    if not Path(args.pairs).exists():
        logger.error("Pairs file not found: %s", args.pairs)
        logger.error("Run first:  python finetune/export_pairs.py")
        sys.exit(1)

    train(
        pairs_path  = args.pairs,
        output_path = args.output,
        base_model  = args.base_model,
        epochs      = args.epochs,
        batch_size  = args.batch_size,
        warmup_ratio= args.warmup,
    )


if __name__ == "__main__":
    main()
