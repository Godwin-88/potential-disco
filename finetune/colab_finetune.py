# ============================================================
# Lex Kenya — BGE-M3 Fine-tuning Notebook (Google Colab)
# ============================================================
# Copy each cell block (separated by # %%) into a Colab cell.
# Run top to bottom. Uses T4 GPU (free tier) or A100 (Colab Pro).
#
# Runtime requirements:
#   - GPU runtime (Runtime → Change runtime type → T4 or A100)
#   - ~4 GB disk for the model
#   - ~15-40 min training depending on GPU and dataset size
# ============================================================

# %% [markdown]
# ## Cell 1 — Install dependencies

# %%
# @title Install dependencies
get_ipython().system('pip install -q sentence-transformers neo4j python-dotenv tqdm')
get_ipython().system('pip install -q torch --index-url https://download.pytorch.org/whl/cu118')
print("✓ Dependencies installed")

# %% [markdown]
# ## Cell 2 — Neo4j credentials

# %%
# @title Neo4j credentials { display-mode: "form" }
# Fill these in — same values as your .env file

NEO4J_URI      = "neo4j+s://4830d4c5.databases.neo4j.io"  # @param {type:"string"}
NEO4J_USER     = "neo4j"                                   # @param {type:"string"}
NEO4J_PASSWORD = "GcOcvDBDjTDTMYKdjji3IwYX2Kf3IGFB-J_jLCgegPU"  # @param {type:"string"}

BASE_MODEL     = "BAAI/bge-m3"                             # @param {type:"string"}
OUTPUT_DIR     = "/content/bge-m3-kenya-legal"             # @param {type:"string"}
EPOCHS         = 3                                          # @param {type:"integer"}
BATCH_SIZE     = 16                                         # @param {type:"integer"}
PAIR_LIMIT     = 5000                                       # @param {type:"integer"}

# Verify Neo4j connection
from neo4j import GraphDatabase

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
driver.verify_connectivity()
print("✓ Neo4j connected to", NEO4J_URI)

# %% [markdown]
# ## Cell 3 — Export citation pairs from Neo4j

# %%
# @title Export training pairs from graph
import json
from tqdm import tqdm

def run_query(cypher, params=None):
    with driver.session() as session:
        result = session.run(cypher, params or {})
        return [record.data() for record in result]

# ── Pair type 1: Case → Section (CITES edges) ─────────────────────────────────
print("Fetching Case → Section pairs…")
pos_rows = run_query("""
    MATCH (c:Case)-[:CITES]->(s:Section)
    WHERE (c.summary IS NOT NULL OR c.headnote IS NOT NULL)
      AND s.text IS NOT NULL
    OPTIONAL MATCH (c)-[:DECIDED_BY]->(court:Court)
    OPTIONAL MATCH (s)-[:PART_OF*1..3]->(act:Act)
    RETURN
        coalesce(c.summary, c.headnote)  AS query,
        s.text                           AS positive,
        c.title                          AS case_name,
        coalesce(act.title, '')          AS act_name,
        coalesce(s.number, '')           AS section_ref
    ORDER BY rand()
    LIMIT $limit
""", {"limit": PAIR_LIMIT})
print(f"  {len(pos_rows)} Case→Section positive pairs")

# Hard negatives: different section from same Act not cited by this case
print("Fetching hard negatives…")
neg_rows = run_query("""
    MATCH (c:Case)-[:CITES]->(cited:Section)-[:PART_OF*1..3]->(act:Act)
                                          <-[:PART_OF*1..3]-(neg:Section)
    WHERE NOT (c)-[:CITES]->(neg)
      AND neg.text IS NOT NULL
      AND elementId(neg) <> elementId(cited)
    WITH c, neg, rand() AS r ORDER BY r
    RETURN
        coalesce(c.summary, c.headnote) AS query,
        neg.text                         AS negative
    LIMIT $limit
""", {"limit": PAIR_LIMIT})

neg_pool = {}
for r in neg_rows:
    neg_pool.setdefault(r["query"], []).append(r["negative"])
print(f"  {len(neg_rows)} hard negatives")

# ── Pair type 2: Case → Article ───────────────────────────────────────────────
print("Fetching Case → Article pairs…")
art_rows = run_query("""
    MATCH (c:Case)-[:CITES]->(a:Article)
    WHERE (c.summary IS NOT NULL OR c.headnote IS NOT NULL)
      AND a.text IS NOT NULL
    RETURN
        coalesce(c.summary, c.headnote) AS query,
        a.text                           AS positive,
        c.title                          AS case_name,
        a.number                         AS article_number
    ORDER BY rand()
    LIMIT $limit
""", {"limit": PAIR_LIMIT})
print(f"  {len(art_rows)} Case→Article pairs")

# ── Assemble dataset ──────────────────────────────────────────────────────────
pairs = []
seen  = set()

def add_pair(query, positive, negative=""):
    q = (query or "").strip()
    p = (positive or "").strip()
    if q and p and len(q) > 30 and q not in seen:
        seen.add(q)
        pairs.append({"query": q, "positive": p, "negative": negative})

for r in pos_rows:
    neg = (neg_pool.get(r["query"], [""])[0])
    add_pair(r["query"], r["positive"], neg)

for r in art_rows:
    add_pair(r["query"], r["positive"])

print(f"\n✓ Total training pairs : {len(pairs)}")
print(f"  With hard negatives  : {sum(1 for p in pairs if p['negative'])}")

# Save to disk (optional, useful if you restart the runtime)
with open("/content/training_pairs.jsonl", "w") as f:
    for p in pairs:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
print("  Saved to /content/training_pairs.jsonl")

# %% [markdown]
# ## Cell 4 — Inspect a few samples

# %%
# @title Preview training pairs
for i, p in enumerate(pairs[:3]):
    print(f"─── Pair {i+1} ───")
    print(f"QUERY:    {p['query'][:200]}")
    print(f"POSITIVE: {p['positive'][:200]}")
    print(f"NEGATIVE: {p['negative'][:200] if p['negative'] else '(none — will use in-batch negatives)'}")
    print()

# %% [markdown]
# ## Cell 5 — Fine-tune BGE-M3

# %%
# @title Fine-tune BGE-M3
import torch
from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Device: {device}")
if device == "cpu":
    print("⚠ No GPU detected. Training will be very slow — switch to GPU runtime.")

# Build InputExamples
examples = []
for p in pairs:
    if p["negative"]:
        examples.append(InputExample(texts=[p["query"], p["positive"], p["negative"]]))
    else:
        examples.append(InputExample(texts=[p["query"], p["positive"]]))

# Train/eval split (95/5)
n_eval   = max(1, int(len(examples) * 0.05))
n_train  = len(examples) - n_eval
train_ex = examples[:n_train]
eval_ex  = examples[n_train:]
print(f"Train: {n_train}  Eval: {n_eval}")

# Load model
print(f"\nLoading {BASE_MODEL}… (downloads ~570 MB on first run)")
model = SentenceTransformer(BASE_MODEL, device=device)
print(f"Embedding dimension: {model.get_sentence_embedding_dimension()}")

# DataLoader + Loss
train_loader = DataLoader(train_ex, shuffle=True, batch_size=BATCH_SIZE)
train_loss   = losses.MultipleNegativesRankingLoss(model)

total_steps  = len(train_loader) * EPOCHS
warmup_steps = int(total_steps * 0.1)
print(f"\nTotal steps: {total_steps}  Warmup: {warmup_steps}")
print(f"Estimated time on T4: ~{total_steps * 0.4 / 60:.0f} min")

# Train
print("\nStarting fine-tuning…")
model.fit(
    train_objectives    = [(train_loader, train_loss)],
    epochs              = EPOCHS,
    warmup_steps        = warmup_steps,
    output_path         = OUTPUT_DIR,
    save_best_model     = True,
    show_progress_bar   = True,
    checkpoint_path     = OUTPUT_DIR + "/checkpoints",
    checkpoint_save_steps = max(100, len(train_loader)),
)
print(f"\n✓ Model saved to {OUTPUT_DIR}")

# %% [markdown]
# ## Cell 6 — Sanity check

# %%
# @title Sanity check — verify similarity improved
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer(OUTPUT_DIR)

# Pick a real pair from the training set
sample_query    = pairs[0]["query"][:300]
sample_positive = pairs[0]["positive"][:300]
sample_negative = pairs[0]["negative"][:300] if pairs[0]["negative"] else pairs[1]["positive"][:300]

vecs = model.encode([sample_query, sample_positive, sample_negative],
                    normalize_embeddings=True)

sim_pos = float(np.dot(vecs[0], vecs[1]))
sim_neg = float(np.dot(vecs[0], vecs[2]))

print(f"Query    : {sample_query[:100]}…")
print(f"Positive : {sample_positive[:100]}…")
print(f"Negative : {sample_negative[:100]}…")
print(f"\nSimilarity (query ↔ positive) : {sim_pos:.4f}  ← should be > 0.6")
print(f"Similarity (query ↔ negative) : {sim_neg:.4f}  ← should be < positive score")
print(f"\nMargin : {sim_pos - sim_neg:.4f}  ← positive = fine-tuning working")

# %% [markdown]
# ## Cell 7 — Save to Google Drive (optional)

# %%
# @title Save model to Google Drive { display-mode: "form" }
SAVE_TO_DRIVE = False  # @param {type:"boolean"}
DRIVE_PATH    = "MyDrive/lex-kenya/bge-m3-kenya-legal"  # @param {type:"string"}

if SAVE_TO_DRIVE:
    from google.colab import drive
    drive.mount("/content/drive")

    import shutil
    dest = f"/content/drive/{DRIVE_PATH}"
    shutil.copytree(OUTPUT_DIR, dest, dirs_exist_ok=True)
    print(f"✓ Model saved to Google Drive: {dest}")
else:
    print("Skipped Drive save. Download manually from the Files panel on the left.")
    print(f"Model is at: {OUTPUT_DIR}")

# %% [markdown]
# ## Cell 8 — Push to Hugging Face Hub (optional)

# %%
# @title Push to HF Hub { display-mode: "form" }
PUSH_TO_HF  = False       # @param {type:"boolean"}
HF_REPO_ID  = "your-username/bge-m3-kenya-legal"  # @param {type:"string"}
HF_TOKEN    = ""          # @param {type:"string"}

if PUSH_TO_HF:
    from huggingface_hub import login
    login(token=HF_TOKEN)
    model = SentenceTransformer(OUTPUT_DIR)
    model.push_to_hub(HF_REPO_ID)
    print(f"✓ Pushed to https://huggingface.co/{HF_REPO_ID}")
else:
    print("Skipped HF Hub push.")

# %% [markdown]
# ## Cell 9 — How to use the fine-tuned model in the API

# %%
# @title Next steps
print("""
╔══════════════════════════════════════════════════════════════════╗
║  HOW TO USE THE FINE-TUNED MODEL IN YOUR API                    ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. Download the model folder from Colab:                        ║
║     Files panel (left sidebar) → right-click OUTPUT_DIR → Download  ║
║     OR use Drive / HF Hub (cells 7–8 above)                     ║
║                                                                  ║
║  2. Put the model in your project:                               ║
║     /home/ed/projects/files/finetune/bge-m3-kenya-legal/         ║
║                                                                  ║
║  3. Update .env:                                                 ║
║     EMBEDDING_BACKEND=local                                      ║
║     HF_EMBEDDING_MODEL=finetune/bge-m3-kenya-legal               ║
║                                                                  ║
║  4. Re-embed all graph nodes with the fine-tuned model:          ║
║     python setup_vector_index.py                                 ║
║                                                                  ║
║  5. Restart the API:                                             ║
║     uvicorn main:app --reload                                    ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
""")
