"""ORM models. Importing this package registers every table on Base.metadata."""

from nexa.models.agents import (
    Agent,
    AgentLanguage,
    AgentRule,
    AgentVersion,
    AgentVoice,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)
from nexa.models.base import Base, TenantScoped
from nexa.models.calls import (
    Call,
    CallEvent,
    CallParticipant,
    Conversation,
    Message,
    ToolExecution,
    Transcript,
    WorkflowExecution,
)
from nexa.models.identity import Tenant, TenantUser, User
from nexa.models.knowledge import Document, DocumentChunk, KnowledgeBase
from nexa.models.ops import AuditLog, UsageRecord
from nexa.models.telephony import PhoneNumber, PhoneRoute
from nexa.models.tools import AgentTool, Integration, IntegrationCredential, Tool, ToolVersion
from nexa.models.voices import Voice

__all__ = [
    "Agent", "AgentLanguage", "AgentRule", "AgentTool", "AgentVersion", "AgentVoice", "AuditLog", "Base",
    "Call", "CallEvent", "CallParticipant", "Conversation", "Document", "DocumentChunk", "Integration",
    "IntegrationCredential", "KnowledgeBase", "Message", "PhoneNumber", "PhoneRoute", "Tenant", "TenantScoped",
    "TenantUser", "Tool", "ToolExecution", "ToolVersion", "Transcript", "UsageRecord", "User", "Voice", "Workflow",
    "WorkflowEdge", "WorkflowExecution", "WorkflowNode",
]
