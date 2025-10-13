from __future__ import annotations

from typing import Any, Dict, List


def _get(d: Dict[str, Any], *names: str) -> Any:
    for n in names:
        if isinstance(d, dict) and n in d:
            return d[n]
    return None


def normalize_content_to_list(content: Any) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    try:
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    t = item.get("type") or ("text" if isinstance(item.get("text"), str) else None)
                    if t == "text" and isinstance(item.get("text"), str):
                        segments.append({"type": "text", "text": item.get("text")})
                    else:
                        seg: Dict[str, Any] = {}
                        if t:
                            seg["type"] = t
                        if isinstance(item.get("text"), str):
                            seg["text"] = item.get("text")
                        if seg:
                            segments.append(seg)
            return segments
        if isinstance(content, dict):
            if isinstance(content.get("text"), str):
                return [{"type": "text", "text": content.get("text")}]
    except Exception:
        return []
    return []


def segments_to_text(segments: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for seg in segments:
        if isinstance(seg, dict) and seg.get("type") == "text" and isinstance(seg.get("text"), str):
            parts.append(seg.get("text") or "")
    return "".join(parts)


def segments_to_warp_results(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for seg in segments:
        if isinstance(seg, dict) and seg.get("type") == "text" and isinstance(seg.get("text"), str):
            results.append({"text": {"text": seg.get("text")}})
    return results 