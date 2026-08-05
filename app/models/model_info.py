from pydantic import BaseModel


class ModelInfo(BaseModel):
    id: str
    kind: str
    provider: str
    endpoint: str
    available: bool
    backend_online: bool


class ModelManagerResponse(BaseModel):
    status: str

    backends: dict[str, bool]

    models: list[ModelInfo]

    totals: dict[str, int]
