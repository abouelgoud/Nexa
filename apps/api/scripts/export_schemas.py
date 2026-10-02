"""Export JSON Schemas from the Pydantic models into packages/agent-schema (keeps Zod/TS in sync)."""

import json
from pathlib import Path

from nexa.schemas.agent_definition import AgentDefinition
from nexa.schemas.tool_definition import ToolDefinition
from nexa.schemas.workflow import WorkflowGraph

OUT = Path(__file__).resolve().parents[3] / "packages" / "agent-schema"

for name, model in {"agent-definition": AgentDefinition, "tool-definition": ToolDefinition,
                    "workflow-graph": WorkflowGraph}.items():
    path = OUT / f"{name}.schema.json"
    path.write_text(json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path}")
