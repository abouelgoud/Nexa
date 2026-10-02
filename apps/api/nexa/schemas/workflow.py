"""Workflow graph definition (React Flow on the frontend, WorkflowEngine at runtime)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeType = Literal[
    "start", "say", "ask", "collect", "condition", "tool", "knowledge_search", "transfer", "wait", "confirm", "end"
]

# Which outgoing handles each node type may use.
NODE_HANDLES: dict[str, set[str] | None] = {
    "start": {"default"},
    "say": {"default"},
    "ask": None,  # "default" or any intent name
    "collect": {"default", "failed"},
    "condition": None,  # any label; edges carry conditions
    "tool": {"success", "error", "default"},
    "knowledge_search": {"found", "not_found", "default"},
    "transfer": {"default"},
    "wait": {"default"},
    "confirm": {"yes", "no", "default"},
    "end": set(),
}


class WorkflowNodeDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,100}$")
    type: NodeType
    label: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


class WorkflowEdgeDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,100}$")
    source: str
    target: str
    handle: str = "default"
    condition: str | None = None
    label: str = ""


class WorkflowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[WorkflowNodeDef]
    edges: list[WorkflowEdgeDef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _structure(self) -> WorkflowGraph:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("Each step in the workflow must have a unique id")
        starts = [n for n in self.nodes if n.type == "start"]
        if len(starts) != 1:
            raise ValueError("The workflow must have exactly one Start step")
        for e in self.edges:
            if e.source not in ids or e.target not in ids:
                raise ValueError(f"Connection {e.id} points to a step that does not exist")
        return self

    def node(self, node_id: str) -> WorkflowNodeDef:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def outgoing(self, node_id: str) -> list[WorkflowEdgeDef]:
        return [e for e in self.edges if e.source == node_id]


class WorkflowIssue(BaseModel):
    node_id: str | None
    severity: Literal["error", "warning"]
    message: str


def validate_workflow(graph: WorkflowGraph, tool_names: set[str] | None = None) -> list[WorkflowIssue]:
    """Business-language validation used by the builder and the publish checklist."""
    issues: list[WorkflowIssue] = []
    # reachability
    start = next(n for n in graph.nodes if n.type == "start")
    seen, stack = set(), [start.id]
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(e.target for e in graph.outgoing(nid))
    for n in graph.nodes:
        name = n.label or n.id
        out = graph.outgoing(n.id)
        if n.id not in seen:
            issues.append(WorkflowIssue(node_id=n.id, severity="warning", message=f'Step "{name}" can never be reached.'))
        if n.type != "end" and n.type != "transfer" and not out:
            issues.append(WorkflowIssue(node_id=n.id, severity="error", message=f'Step "{name}" has no next step.'))
        allowed = NODE_HANDLES[n.type]
        if allowed is not None:
            for e in out:
                if e.handle not in allowed:
                    issues.append(WorkflowIssue(node_id=n.id, severity="error",
                                                message=f'Step "{name}" has an unknown branch "{e.handle}".'))
        c = n.config
        if n.type == "say" and not (c.get("text") or c.get("text_en")):
            issues.append(WorkflowIssue(node_id=n.id, severity="error", message=f'"{name}" has nothing to say.'))
        if n.type == "ask" and not c.get("question"):
            issues.append(WorkflowIssue(node_id=n.id, severity="error", message=f'"{name}" is missing its question.'))
        if n.type == "collect" and not c.get("variable"):
            issues.append(WorkflowIssue(node_id=n.id, severity="error",
                                        message=f'"{name}" does not say which information to collect.'))
        if n.type == "confirm" and not c.get("text"):
            issues.append(WorkflowIssue(node_id=n.id, severity="error",
                                        message=f'"{name}" is missing the confirmation question.'))
        if n.type == "confirm":
            handles = {e.handle for e in out}
            if not {"yes", "no"} <= handles:
                issues.append(WorkflowIssue(node_id=n.id, severity="error",
                                            message=f'"{name}" needs both a "yes" and a "no" path.'))
        if n.type == "tool":
            tool = c.get("tool")
            if not tool:
                issues.append(WorkflowIssue(node_id=n.id, severity="error",
                                            message=f'"{name}" does not have an action selected.'))
            elif tool_names is not None and tool not in tool_names:
                issues.append(WorkflowIssue(node_id=n.id, severity="error",
                                            message=f'"{name}" uses the action "{tool}" which is not enabled for this agent.'))
        if n.type == "condition":
            if not any(e.condition in (None, "", "else") or e.handle == "else" for e in out):
                issues.append(WorkflowIssue(node_id=n.id, severity="warning",
                                            message=f'"{name}" has no "otherwise" path.'))
    return issues
