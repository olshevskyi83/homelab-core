from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Ingestion DTO
# Labs submit approved artifacts; this DTO does not expose lifecycle actions.
class KnowledgeDocumentRegistration(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    document_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    source_type: str = Field(
        default="document",
        min_length=1,
        max_length=100,
    )
    project: str = Field(
        default="document-lab",
        min_length=1,
        max_length=100,
    )
    source_filename: str | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
    )


class KnowledgeTranscriptionRegistration(BaseModel):
    """Audio Lab session transcript registration under the server-owned root."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=255)
    text_path: str = Field(min_length=1, max_length=4096)
    source_filename: str = Field(min_length=1, max_length=1024)


# Knowledge Management DTOs
# These contracts belong to the central Knowledge Manager.
class KnowledgeBulkRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=200)


class KnowledgeDeleteAllRequest(BaseModel):
    confirmation: Literal["DELETE ALL KNOWLEDGE"]


class KnowledgePurgeDeletedRequest(BaseModel):
    confirmation: Literal["PURGE DELETED REGISTRY"]


# Compatibility DTOs
# Direct search/chat remains available for existing API clients. Labs should
# not build UI against these contracts; Open WebUI is the chat client.
class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=20)
    source_type: str | None = None
    project: str | None = None
    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )


class KnowledgeChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="qwen-general", min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    source_type: str | None = None
    project: str | None = None
    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
