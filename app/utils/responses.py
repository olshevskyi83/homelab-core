import httpx
from fastapi.responses import Response


def proxy_response(response: httpx.Response) -> Response:
    content_type = response.headers.get(
        "content-type",
        "application/json",
    )

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=content_type.split(";")[0],
    )
