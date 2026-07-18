from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.entities import CodeEntity, PaperEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.domain.index_manifest import SymbolChunk
from backend.app.persistence.index_store import IndexArtifacts, StructuredIndexStore


CODE_REPO_ID = "repo_benchmark_code"
ISOLATION_REPO_ID = "repo_benchmark_isolation"


def build_fixture(path: str | Path) -> dict[str, str]:
    store = StructuredIndexStore(path)
    versions: dict[str, str] = {}
    for key, repo_id, repository_key, input_hash, suffix in (
        ("v1", CODE_REPO_ID, "benchmark/code", "benchmark-v1", ""),
        ("v2", CODE_REPO_ID, "benchmark/code", "benchmark-v2", "\n# fixture version 2"),
        ("isolation_v1", ISOLATION_REPO_ID, "benchmark/isolation", "benchmark-isolation-v1", ""),
    ):
        lease = store.begin_version(
            repo_id=repo_id,
            identity_mode="explicit",
            repository_key=repository_key,
            display_name=repository_key,
            input_hash=input_hash,
        )
        store.mark_ready(lease)
        store.activate(lease, _artifacts(repo_id, suffix=suffix))
        versions[key] = lease.index_version_id
    return versions


def _artifacts(repo_id: str, *, suffix: str) -> IndexArtifacts:
    specs = [
        ("ent_repository", "repository", ".", "benchmark", "benchmark", None,
         "Small PyTorch repository with model, dataset, training, inference, and configuration."),
        ("ent_model_file", "file", "models/simple_model.py", "simple_model.py", "models.simple_model", "ent_repository",
         "Module defining the SimpleNet neural network and its linear layers."),
        ("ent_simple_net", "class", "models/simple_model.py", "SimpleNet", "models.simple_model.SimpleNet", "ent_model_file",
         "class SimpleNet(nn.Module): two Linear layers fc1 and fc2; forward performs inference."),
        ("ent_init", "method", "models/simple_model.py", "__init__", "models.simple_model.SimpleNet.__init__", "ent_simple_net",
         "def __init__(self):\n    self.fc1 = nn.Linear(4, 8)\n    self.fc2 = nn.Linear(8, 2)"),
        ("ent_forward", "method", "models/simple_model.py", "forward", "models.simple_model.SimpleNet.forward", "ent_simple_net",
         "def forward(self, x):\n    hidden = torch.relu(self.fc1(x))\n    return self.fc2(hidden)" + suffix),
        ("ent_fc1", "model_module", "models/simple_model.py", "fc1", "models.simple_model.SimpleNet.fc1", "ent_simple_net",
         "fc1 is the first linear layer: nn.Linear(4, 8), mapping input features to hidden features."),
        ("ent_fc2", "model_module", "models/simple_model.py", "fc2", "models.simple_model.SimpleNet.fc2", "ent_simple_net",
         "fc2 is the second linear output layer: nn.Linear(8, 2), producing model logits."),
        ("ent_train_file", "file", "train.py", "train.py", "train", "ent_repository",
         "Training module containing train_one_epoch and the main training entry."),
        ("ent_train", "function", "train.py", "train_one_epoch", "train.train_one_epoch", "ent_train_file",
         "def train_one_epoch(model, loader, optimizer):\n    for inputs, labels in loader:\n        logits = model(inputs)\n        loss = cross_entropy(logits, labels)\n        loss.backward()\n        optimizer.step()\n# inputs shape is batch by 4; model(batch) remains an unresolved dynamic call"),
        ("ent_main", "training_entry", "train.py", "main", "train.main", "ent_train_file",
         "def main():\n    model = SimpleNet()\n    train_one_epoch(model, loader, optimizer)"),
        ("ent_config", "config", "config.yaml", "config.yaml", "config", "ent_repository",
         "training configuration: epochs: 5, batch_size: 16, learning_rate: 0.001"),
        ("ent_dataset", "dataset", "dataset.py", "TinyDataset", "dataset.TinyDataset", "ent_repository",
         "class TinyDataset(Dataset): stores feature tensors and labels for training."),
        ("ent_getitem", "method", "dataset.py", "__getitem__", "dataset.TinyDataset.__getitem__", "ent_dataset",
         "def __getitem__(self, index):\n    return self.features[index], self.labels[index]"),
    ]
    code_entities: list[CodeEntity] = []
    evidence: list[EvidenceRef] = []
    chunks: list[SymbolChunk] = []
    for ordinal, (entity_id, entity_type, path, name, qualified, parent_id, text) in enumerate(specs):
        evidence_id = f"ev_{entity_id}"
        digest = _hash(text)
        start_line = 1
        end_line = max(1, text.count("\n") + 1)
        evidence.append(EvidenceRef(
            id=evidence_id,
            source_type="code",
            entity_id=entity_id,
            file_path=path,
            start_line=start_line,
            end_line=end_line,
            content_hash=digest,
        ))
        code_entities.append(CodeEntity(
            id=entity_id,
            repo_id=repo_id,
            entity_type=entity_type,
            path=path,
            name=name,
            qualified_name=qualified,
            parent_id=parent_id,
            start_line=start_line,
            end_line=end_line,
            source_code=text,
            content_hash=digest,
            evidence_refs=[evidence_id],
        ))
        chunks.append(SymbolChunk(
            id=entity_id.replace("ent_", "chunk_"),
            repo_id=repo_id,
            entity_id=entity_id,
            entity_kind="code",
            chunk_type=_chunk_type(entity_type),
            path=path,
            start_line=start_line,
            end_line=end_line,
            ordinal=ordinal,
            text=text,
            content_hash=digest,
            char_count=len(text),
            metadata={"canonical": True},
        ))

    paper_specs = [
        ("ent_paper_method", "method_module", "Method", 2,
         "The paper method uses a two-layer neural network. The method aligns with SimpleNet forward."),
        ("ent_paper_figure", "figure", "Figure 1", 3,
         "Figure 1 shows input, first linear hidden layer, second linear output layer, and SimpleNet."),
    ]
    paper_entities: list[PaperEntity] = []
    for ordinal, (entity_id, entity_type, title, page, text) in enumerate(paper_specs):
        evidence_id = f"ev_{entity_id}"
        digest = _hash(text)
        evidence.append(EvidenceRef(
            id=evidence_id,
            source_type="paper" if entity_type != "figure" else "figure",
            entity_id=entity_id,
            paper_id="paper_benchmark",
            page_number=page,
            figure_id="figure-1" if entity_type == "figure" else None,
            content_hash=digest,
        ))
        paper_entities.append(PaperEntity(
            id=entity_id,
            paper_id="paper_benchmark",
            entity_type=entity_type,
            title=title,
            text=text,
            page_number=page,
            content_hash=digest,
            evidence_refs=[evidence_id],
        ))
        chunks.append(SymbolChunk(
            id=entity_id.replace("ent_", "chunk_"),
            repo_id=repo_id,
            entity_id=entity_id,
            entity_kind="paper",
            chunk_type="paper_entity",
            page_number=page,
            ordinal=ordinal,
            text=text,
            content_hash=digest,
            char_count=len(text),
            metadata={"canonical": True},
        ))

    edge_specs = [
        ("edge_repo_model", "ent_repository", "ent_model_file", "CONTAINS"),
        ("edge_model_class", "ent_model_file", "ent_simple_net", "DEFINES"),
        ("edge_class_forward", "ent_simple_net", "ent_forward", "DEFINES"),
        ("edge_forward_fc1", "ent_forward", "ent_fc1", "CALLS"),
        ("edge_forward_fc2", "ent_forward", "ent_fc2", "CALLS"),
        ("edge_main_train", "ent_main", "ent_train", "CALLS"),
        ("edge_main_model", "ent_main", "ent_simple_net", "INSTANTIATES"),
        ("edge_paper_forward", "ent_paper_method", "ent_forward", "ALIGNS_WITH"),
        ("edge_cycle_a", "ent_train", "ent_main", "CALLS"),
        ("edge_cycle_b", "ent_main", "ent_train", "CALLS"),
    ]
    edges = [KnowledgeEdge(
        id=edge_id,
        repo_id=repo_id,
        source_id=source,
        target_id=target,
        edge_type=edge_type,
        confidence=1.0,
        resolution_type="exact",
    ) for edge_id, source, target, edge_type in edge_specs]
    edges.append(KnowledgeEdge(
        id="edge_train_unresolved",
        repo_id=repo_id,
        source_id="ent_train",
        edge_type="CALLS",
        confidence=0.5,
        resolution_type="unresolved",
        unresolved_symbol="model(batch)",
    ))
    return IndexArtifacts([], code_entities, paper_entities, edges, evidence, chunks)


def _chunk_type(entity_type: str) -> str:
    if entity_type in {"method"}:
        return "method"
    if entity_type in {"function", "training_entry", "inference_entry"}:
        return "function"
    if entity_type in {"class", "dataset"}:
        return "class"
    if entity_type == "model_module":
        return "model_module"
    return "file"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the immutable v1.5 retrieval benchmark fixture.")
    parser.add_argument("output")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing fixture: {output}")
    print(build_fixture(output))


if __name__ == "__main__":
    main()
