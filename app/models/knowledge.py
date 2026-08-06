from pydantic import BaseModel, Field


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
