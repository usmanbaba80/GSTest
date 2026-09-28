"""Normalize ScrapingDog Google AI Mode responses into one frontend-friendly schema."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


AI_SCHEMA_VERSION = 2

# Frontend can switch on these block types only.
KNOWN_BLOCK_TYPES = (
    "paragraph",
    "heading",
    "list",
    "table",
    "code",
    "product",
    "unknown",
)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _text_from(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("snippet", "text", "title", "name", "value", "content", "markdown"):
            if key in value and value[key] is not None:
                return _text_from(value[key])
        return ""
    if isinstance(value, list):
        parts = [_text_from(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    return str(value).strip()


def _strip_api_key_from_url(url: str) -> str:
    """Remove api_key query params so secrets are never sent to the frontend."""
    if not url or "api_key=" not in url:
        return url
    parts = urlsplit(url)
    filtered = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() != "api_key"
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment))


def _normalize_links(value: Any) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    for item in _as_list(value):
        if isinstance(item, str):
            url = item.strip()
            if url:
                links.append({"text": "", "url": _strip_api_key_from_url(url)})
            continue
        if not isinstance(item, dict):
            continue
        url = _text_from(item.get("link") or item.get("url") or item.get("href"))
        text = _text_from(item.get("anchor") or item.get("text") or item.get("title"))
        if url or text:
            links.append({"text": text, "url": _strip_api_key_from_url(url)})
    return links


def _empty_block(block_type: str = "unknown") -> Dict[str, Any]:
    return {
        "type": block_type if block_type in KNOWN_BLOCK_TYPES else "unknown",
        "text": "",
        "level": None,
        "items": [],
        "headers": [],
        "rows": [],
        "links": [],
        "language": None,
        "product": None,
    }


def _normalize_list_items(items: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in _as_list(items):
        if isinstance(item, dict) and item.get("type") == "list":
            nested = _normalize_list_items(item.get("items") or item.get("list") or [])
            normalized.extend(nested)
            continue

        text = _text_from(item)
        links = _normalize_links(item.get("links") if isinstance(item, dict) else [])
        nested_items: List[Dict[str, Any]] = []
        if isinstance(item, dict):
            nested_raw = item.get("items") or item.get("list")
            if nested_raw:
                nested_items = _normalize_list_items(nested_raw)

        if text or links or nested_items:
            normalized.append(
                {
                    "text": text,
                    "links": links,
                    "items": nested_items,
                }
            )
    return normalized


def _normalize_table(block: Dict[str, Any]) -> Dict[str, Any]:
    out = _empty_block("table")
    headers: List[str] = []
    rows: List[List[str]] = []

    if isinstance(block.get("headers"), list):
        headers = [_text_from(h) for h in block["headers"]]
    elif isinstance(block.get("columns"), list):
        headers = [_text_from(h) for h in block["columns"]]

    raw_rows = block.get("rows")
    if raw_rows is None:
        raw_rows = block.get("table")
    if raw_rows is None and isinstance(block.get("data"), list):
        raw_rows = block.get("data")

    for row in _as_list(raw_rows):
        if isinstance(row, dict):
            if headers:
                rows.append([_text_from(row.get(h)) for h in headers])
            else:
                if not headers:
                    headers = [_text_from(k) for k in row.keys()]
                rows.append([_text_from(v) for v in row.values()])
        elif isinstance(row, list):
            rows.append([_text_from(cell) for cell in row])
        else:
            rows.append([_text_from(row)])

    markdown = _text_from(block.get("markdown") or block.get("snippet") or block.get("text"))
    out["headers"] = headers
    out["rows"] = rows
    out["text"] = markdown
    out["links"] = _normalize_links(block.get("links"))
    return out


def _normalize_product_payload(product: Any) -> Dict[str, Any]:
    if not isinstance(product, dict):
        return {
            "title": _text_from(product),
            "url": "",
            "price": "",
            "old_price": "",
            "extracted_price": None,
            "extracted_old_price": None,
            "source": "",
            "thumbnail": "",
            "page_token": "",
        }

    url = _text_from(
        product.get("product_link")
        or product.get("link")
        or product.get("url")
    )
    return {
        "title": _text_from(product.get("title")),
        "url": _strip_api_key_from_url(url),
        "price": _text_from(product.get("price")),
        "old_price": _text_from(product.get("old_price")),
        "extracted_price": product.get("extracted_price"),
        "extracted_old_price": product.get("extracted_old_price"),
        "source": _text_from(product.get("source")),
        "thumbnail": _text_from(product.get("thumbnail")),
        "page_token": _text_from(product.get("immersive_product_page_token")),
    }


def _normalize_product_block(block: Dict[str, Any]) -> Dict[str, Any]:
    out = _empty_block("product")
    product_raw = block.get("inline_product") or block.get("product") or block
    product = _normalize_product_payload(product_raw)
    out["product"] = product
    out["text"] = product.get("title") or ""
    if product.get("url"):
        out["links"] = [{"text": product.get("title") or "", "url": product["url"]}]
    return out


def _normalize_block(block: Any) -> Dict[str, Any]:
    if not isinstance(block, dict):
        out = _empty_block("paragraph")
        out["text"] = _text_from(block)
        return out

    raw_type = str(block.get("type") or "unknown").strip().lower()
    if raw_type in ("list_item", "bullet", "unordered_list", "ordered_list"):
        raw_type = "list"
    if raw_type in ("code_block", "codeblock", "pre"):
        raw_type = "code"
    if raw_type in ("inline_product", "product_card", "shopping_item"):
        raw_type = "product"

    if raw_type not in KNOWN_BLOCK_TYPES:
        if block.get("inline_product") is not None or (
            isinstance(block.get("product"), dict)
            and (block.get("product_link") or block["product"].get("product_link") or block["product"].get("title"))
        ):
            raw_type = "product"
        elif block.get("headers") is not None or block.get("rows") is not None or block.get("table") is not None:
            raw_type = "table"
        elif block.get("items") is not None or block.get("list") is not None:
            raw_type = "list"
        elif block.get("level") is not None or "heading" in raw_type:
            raw_type = "heading"
        elif block.get("code") is not None or block.get("language") is not None:
            raw_type = "code"
        elif _text_from(block):
            raw_type = "paragraph"
        else:
            raw_type = "unknown"

    if raw_type == "product":
        return _normalize_product_block(block)

    if raw_type == "table":
        return _normalize_table(block)

    if raw_type == "list":
        out = _empty_block("list")
        items = _normalize_list_items(block.get("items") or block.get("list") or [])
        out["items"] = items
        out["text"] = "\n".join(item["text"] for item in items if item.get("text"))
        out["links"] = _normalize_links(block.get("links"))
        return out

    if raw_type == "heading":
        out = _empty_block("heading")
        out["text"] = _text_from(block.get("text") or block.get("snippet") or block)
        level = block.get("level")
        try:
            out["level"] = int(level) if level is not None else 2
        except (TypeError, ValueError):
            out["level"] = 2
        out["links"] = _normalize_links(block.get("links"))
        return out

    if raw_type == "code":
        out = _empty_block("code")
        out["text"] = _text_from(block.get("code") or block.get("snippet") or block.get("text") or block)
        out["language"] = _text_from(block.get("language")) or None
        out["links"] = _normalize_links(block.get("links"))
        return out

    if raw_type == "paragraph":
        out = _empty_block("paragraph")
        out["text"] = _text_from(block.get("snippet") or block.get("text") or block)
        out["links"] = _normalize_links(block.get("links"))
        return out

    out = _empty_block("unknown")
    out["text"] = _text_from(block)
    out["links"] = _normalize_links(block.get("links"))
    return out


def _normalize_reference(item: Any, index: int) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "index": index,
            "title": _text_from(item),
            "url": "",
            "snippet": "",
            "source": "",
            "thumbnail": "",
        }
    return {
        "index": item.get("index", index),
        "title": _text_from(item.get("title")),
        "url": _strip_api_key_from_url(_text_from(item.get("link") or item.get("url"))),
        "snippet": _text_from(item.get("snippet")),
        "source": _text_from(item.get("source")),
        "thumbnail": _text_from(item.get("thumbnail") or item.get("favicon")),
    }


def _normalize_image(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": "", "url": _text_from(item), "thumbnail": "", "source": ""}
    return {
        "title": _text_from(item.get("title")),
        "url": _strip_api_key_from_url(_text_from(item.get("link") or item.get("url"))),
        "thumbnail": _text_from(item.get("thumbnail") or item.get("image")),
        "source": _text_from(item.get("source")),
    }


def _normalize_video(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": "", "url": _text_from(item), "thumbnail": "", "source": "", "duration": ""}
    return {
        "title": _text_from(item.get("title")),
        "url": _strip_api_key_from_url(_text_from(item.get("link") or item.get("url"))),
        "thumbnail": _text_from(item.get("thumbnail")),
        "source": _text_from(item.get("source") or item.get("channel")),
        "duration": _text_from(item.get("duration") or item.get("length")),
    }


def _normalize_shopping(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": _text_from(item), "url": "", "price": "", "source": "", "thumbnail": ""}
    return {
        "title": _text_from(item.get("title")),
        "url": _strip_api_key_from_url(_text_from(item.get("link") or item.get("url"))),
        "price": _text_from(item.get("price")),
        "source": _text_from(item.get("source") or item.get("seller")),
        "thumbnail": _text_from(item.get("thumbnail")),
    }


def _normalize_local(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": _text_from(item), "address": "", "rating": "", "url": ""}
    return {
        "title": _text_from(item.get("title") or item.get("name")),
        "address": _text_from(item.get("address")),
        "rating": _text_from(item.get("rating")),
        "url": _strip_api_key_from_url(_text_from(item.get("link") or item.get("url"))),
    }


def is_normalized_ai_payload(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == AI_SCHEMA_VERSION
        and isinstance(payload.get("blocks"), list)
    )


def normalize_ai_mode_response(raw: Optional[Dict[str, Any]], query: str = "") -> Dict[str, Any]:
    """
    Convert any ScrapingDog AI Mode JSON into a stable shape.

    Known text_blocks types handled:
    - paragraph, heading, list, table, code/code_block
    - inline_product -> product
    - anything else  -> unknown (best-effort text)
    """
    if is_normalized_ai_payload(raw):
        return raw  # type: ignore[return-value]

    source = raw if isinstance(raw, dict) else {}
    blocks = [_normalize_block(block) for block in _as_list(source.get("text_blocks"))]

    # Upgrade older normalized payloads (schema v1) that already have blocks
    if not blocks and isinstance(source.get("blocks"), list):
        blocks = [_normalize_block(block) for block in source["blocks"]]

    blocks = [
        block
        for block in blocks
        if block.get("text")
        or block.get("items")
        or block.get("rows")
        or block.get("headers")
        or block.get("links")
        or block.get("product")
    ]

    references = [
        _normalize_reference(item, index)
        for index, item in enumerate(_as_list(source.get("references")))
    ]
    images = [_normalize_image(item) for item in _as_list(source.get("inline_images"))]
    videos = [
        _normalize_video(item)
        for item in _as_list(source.get("inline_videos") or source.get("videos"))
    ]
    shopping = [_normalize_shopping(item) for item in _as_list(source.get("shopping_results"))]
    local_results = [_normalize_local(item) for item in _as_list(source.get("local_results"))]

    for block in blocks:
        if block.get("type") == "product" and isinstance(block.get("product"), dict):
            product = block["product"]
            shopping.append(
                {
                    "title": product.get("title") or "",
                    "url": product.get("url") or "",
                    "price": product.get("price") or "",
                    "source": product.get("source") or "",
                    "thumbnail": product.get("thumbnail") or "",
                }
            )

    return {
        "schema_version": AI_SCHEMA_VERSION,
        "query": query or _text_from(source.get("query")),
        "blocks": blocks,
        "references": references,
        "images": images,
        "videos": videos,
        "shopping": shopping,
        "local_results": local_results,
        "block_types_present": sorted({block["type"] for block in blocks}),
    }
