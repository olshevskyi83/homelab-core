import json
import re
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.services import knowledge_service


router = APIRouter(prefix="/v1", tags=["openai-compatible"])

KNOWLEDGE_MODEL_ID = "homelab-knowledge"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: Any


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)

    return ""


def _conversation(request: ChatCompletionRequest) -> tuple[str, list[dict]]:
    messages = [
        {
            "role": message.role,
            "content": _content_text(message.content),
        }
        for message in request.messages
        if message.role in {"user", "assistant"}
        and _content_text(message.content).strip()
    ]

    query = next(
        (
            message["content"]
            for message in reversed(messages)
            if message["role"] == "user"
        ),
        "",
    ).strip()

    if not query:
        raise ValueError("Chat request contains no user message")

    return query, messages


def _answer_with_sources(result: dict) -> str:
    answer = str(result.get("answer") or "").strip()
    sources = result.get("sources") or []

    if not sources:
        return answer

    cited_numbers = {
        int(number)
        for number in re.findall(r"\[Джерело\s+(\d+)\]", answer)
    }

    if cited_numbers:
        sources = [
            source
            for source in sources
            if source.get("number") in cited_numbers
        ]

    lines = ["", "---", "Джерела:"]
    for source in sources:
        number = source.get("number")
        filename = source.get("source_filename") or "Без назви"
        score = source.get("score")
        score_text = f" — {float(score):.3f}" if score is not None else ""
        lines.append(f"[{number}] {filename}{score_text}")

    return answer + "\n".join(lines)


@router.get("/models")
async def list_knowledge_models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": KNOWLEDGE_MODEL_ID,
                "name": "Homelab Knowledge",
                "object": "model",
                "created": 0,
                "owned_by": "homelab-core",
            }
        ],
    }


@router.post("/chat/completions")
async def knowledge_chat_completion(request: ChatCompletionRequest):
    if request.model != KNOWLEDGE_MODEL_ID:
        raise HTTPException(status_code=404, detail="Model not found")

    try:
        query, messages = _conversation(request)
        result = await knowledge_service.chat_with_knowledge(
            query,
            model=settings.knowledge_chat_model,
            conversation_messages=messages,
            limit=settings.knowledge_chat_limit,
            temperature=request.temperature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    content = _answer_with_sources(result)
    completion_id = f"chatcmpl-{uuid4().hex}"
    created = int(time.time())

    if request.stream:
        async def events():
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            done = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": request.model,
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": "stop"}
                ],
            }
            yield f"data: {json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": result.get("usage"),
    }
