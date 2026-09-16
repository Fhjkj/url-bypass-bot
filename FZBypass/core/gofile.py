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
    token = (
        os.getenv("GOFILE_API_TOKEN")
        or os.getenv("GOFILE_API_KEY")
        or os.getenv("GOFILE_TOKEN")
    )
    if not token:
        raise DDLException("GoFile API credentials are not configured")
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    code = url.rstrip("/").split("/")[-1]
    timeout = ClientTimeout(total=30)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with ClientSession(timeout=timeout, headers=headers) as session:
        endpoint = f"https://api.gofile.io/contents/{code}"
        async with session.get(endpoint) as response:
            if response.status in {401, 403}:
                async with session.get(f"{endpoint}?token={token}", headers={"Accept": "application/json"}) as retry:
                    if retry.status in {401, 403}:
                        raise DDLException("GoFile API authorization failed: token rejected")
                    if retry.status != 200:
                        raise DDLException(f"GoFile API returned HTTP {retry.status}")
                    payload = await retry.json(content_type=None)
            else:
                if response.status != 200:
                    raise DDLException(f"GoFile API returned HTTP {response.status}")
                payload = await response.json(content_type=None)

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
