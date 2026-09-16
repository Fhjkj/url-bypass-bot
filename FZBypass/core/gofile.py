import os
from dataclasses import dataclass

from aiohttp import ClientSession, ClientTimeout

from FZBypass.core.exceptions import DDLException


@dataclass
class GofileResult:
    filename: str
    total_size: str
    file_count: int
    links: list[tuple[str, str]]


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def _files(node: dict):
    children = node.get("children")
    if isinstance(children, dict):
        for child in children.values():
            if isinstance(child, dict):
                yield from _files(child)
    elif node.get("type") == "file":
        yield node


async def gofile(url: str) -> GofileResult:
    """Read a GoFile share through the official authenticated contents API."""
    raw_tokens = [
        os.getenv("GOFILE_API_TOKEN"),
        os.getenv("GOFILE_API_KEY"),
        os.getenv("GOFILE_TOKEN"),
    ]
    tokens = []
    for raw_token in raw_tokens:
        if not raw_token:
            continue
        token = raw_token.strip().strip('"\'')
        if token.lower().startswith("bearer "):
            token = token[7:].strip().strip('"\'')
        if token and token not in tokens:
            tokens.append(token)
    if not tokens:
        raise DDLException("GoFile API credentials are not configured")
    code = url.rstrip("/").split("/")[-1]
    timeout = ClientTimeout(total=30)
    async with ClientSession(timeout=timeout) as session:
        endpoint = f"https://api.gofile.io/contents/{code}"
        payload = None
        last_status = 401
        for token in tokens:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            async with session.get(endpoint, headers=headers) as response:
                last_status = response.status
                if response.status == 200:
                    payload = await response.json(content_type=None)
                    break
            async with session.get(f"{endpoint}?token={token}", headers={"Accept": "application/json"}) as retry:
                last_status = retry.status
                if retry.status == 200:
                    payload = await retry.json(content_type=None)
                    break
        if payload is None:
            if last_status in {401, 403}:
                raise DDLException("GoFile API authorization failed: all configured tokens rejected")
            raise DDLException(f"GoFile API returned HTTP {last_status}")

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise DDLException("GoFile API returned no content metadata")
    files = list(_files(data))
    if not files:
        raise DDLException("GoFile share contains no downloadable files")
    total = sum(int(item.get("size") or 0) for item in files)
    links = []
    for item in files:
        link = item.get("link") or item.get("downloadPage")
        if isinstance(link, str) and link.startswith(("http://", "https://")):
            links.append(("Download", link))
    if not links:
        links = [("Download", url)]
    first_name = files[0].get("name") or data.get("name") or "GoFile content"
    return GofileResult(str(first_name), _format_size(total), len(files), links)
