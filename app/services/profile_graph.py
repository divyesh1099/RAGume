from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Document, ProfileClaim, ProfileGraphEdge, ProfileGraphNode
from app.services.claim_utils import extract_claim_entities


def sync_profile_graph(session: Session) -> tuple[int, int]:
    session.flush()
    approved_claim_rows = session.execute(
        select(ProfileClaim, Document)
        .join(Document, ProfileClaim.document_id == Document.id)
        .order_by(Document.profile_id.asc(), ProfileClaim.created_at.asc())
    ).all()

    session.execute(delete(ProfileGraphEdge))
    session.execute(delete(ProfileGraphNode))
    session.flush()

    node_specs: dict[str, dict] = {}
    edge_specs: dict[tuple[str, str, str], dict] = {}

    def ensure_node(node_key: str, node_type: str, label: str, metadata: dict | None = None) -> None:
        current = node_specs.get(node_key)
        if current is None:
            node_specs[node_key] = {
                "node_key": node_key,
                "node_type": node_type,
                "label": label,
                "weight": 1.0,
                "node_metadata": metadata or {},
            }
        else:
            current["weight"] += 1.0

    def add_edge(source_key: str, target_key: str, relation_type: str, metadata: dict | None = None) -> None:
        edge_key = (source_key, target_key, relation_type)
        current = edge_specs.get(edge_key)
        if current is None:
            edge_specs[edge_key] = {
                "source_key": source_key,
                "target_key": target_key,
                "relation_type": relation_type,
                "weight": 1.0,
                "edge_metadata": metadata or {},
            }
        else:
            current["weight"] += 1.0

    for claim, document in approved_claim_rows:
        profile_id = document.profile_id
        claim_key = f"profile:{profile_id}:claim:{claim.claim_id}"
        category_key = f"profile:{profile_id}:category:{claim.category}"
        document_name = (claim.evidence or {}).get("document_filename") or claim.document_id
        document_key = f"profile:{profile_id}:document:{claim.document_id}"

        ensure_node(claim_key, "claim", claim.text, {"claim_id": claim.claim_id, "profile_id": profile_id})
        ensure_node(category_key, "category", claim.category.replace("_", " "), {"profile_id": profile_id})
        ensure_node(document_key, "document", document_name, {"document_id": claim.document_id, "profile_id": profile_id})
        add_edge(claim_key, category_key, "classified_as", {"profile_id": profile_id})
        add_edge(claim_key, document_key, "supported_by", {"profile_id": profile_id})

        entities = extract_claim_entities(claim.text, claim.skills, claim.category)
        entity_keys: list[str] = []
        for entity in entities:
            entity_key = f"profile:{profile_id}:{entity['type']}:{entity['normalized']}"
            ensure_node(entity_key, entity["type"], entity["name"], {"profile_id": profile_id})
            add_edge(claim_key, entity_key, f"mentions_{entity['type']}", {"profile_id": profile_id})
            entity_keys.append(entity_key)

        skill_keys = [key for key in entity_keys if ":skill:" in key]
        for index, source_key in enumerate(skill_keys):
            for target_key in skill_keys[index + 1 :]:
                ordered = tuple(sorted((source_key, target_key)))
                add_edge(ordered[0], ordered[1], "co_occurs", {"profile_id": profile_id})

    for spec in node_specs.values():
        session.add(
            ProfileGraphNode(
                profile_id=spec["node_metadata"].get("profile_id"),
                node_key=spec["node_key"],
                node_type=spec["node_type"],
                label=spec["label"],
                weight=spec["weight"],
                node_metadata=spec["node_metadata"],
            )
        )
    session.flush()

    persisted_nodes = list(session.scalars(select(ProfileGraphNode)).all())
    nodes_by_key = {node.node_key: node for node in persisted_nodes}

    for spec in edge_specs.values():
        source = nodes_by_key.get(spec["source_key"])
        target = nodes_by_key.get(spec["target_key"])
        if source is None or target is None:
            continue
        session.add(
            ProfileGraphEdge(
                profile_id=spec["edge_metadata"].get("profile_id"),
                source_node_id=source.id,
                target_node_id=target.id,
                relation_type=spec["relation_type"],
                weight=spec["weight"],
                edge_metadata=spec["edge_metadata"],
            )
        )

    session.flush()
    return len(node_specs), len(edge_specs)
