"""Acyclic evidence lineage graph."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Literal, Self

from pydantic import Field, model_validator

from ehrfs.domain.models import DomainModel

NodeKind = Literal["raw", "canonical", "mapping", "quality", "omop", "catalog"]


class LineageNode(DomainModel):
    node_id: str
    kind: NodeKind
    label: str
    metadata: dict[str, str] = Field(default_factory=dict)


class LineageEdge(DomainModel):
    source_node_id: str
    target_node_id: str
    relation: str


class LineageGraph(DomainModel):
    nodes: tuple[LineageNode, ...]
    edges: tuple[LineageEdge, ...]

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            msg = "Lineage node IDs must be unique"
            raise ValueError(msg)
        for edge in self.edges:
            if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
                msg = "Every lineage edge must reference existing nodes"
                raise ValueError(msg)
        indegree = dict.fromkeys(node_ids, 0)
        outgoing: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            outgoing[edge.source_node_id].append(edge.target_node_id)
            indegree[edge.target_node_id] += 1
        queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
        visited = 0
        while queue:
            source = queue.popleft()
            visited += 1
            for target in outgoing[source]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if visited != len(node_ids):
            msg = "Lineage graphs must be acyclic"
            raise ValueError(msg)
        return self
