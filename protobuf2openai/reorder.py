from __future__ import annotations

from typing import Dict, List, Optional
from .models import ChatMessage
from .helpers import normalize_content_to_list, segments_to_text


def reorder_messages_for_anthropic(history: List[ChatMessage]) -> List[ChatMessage]:
    if not history:
        return []

    expanded: List[ChatMessage] = []
    for m in history:
        if m.role == "user":
            items = normalize_content_to_list(m.content)
            if isinstance(m.content, list) and len(items) > 1:
                for seg in items:
                    if isinstance(seg, dict) and seg.get("type") == "text" and isinstance(seg.get("text"), str):
                        expanded.append(ChatMessage(role="user", content=seg.get("text")))
                    else:
                        expanded.append(ChatMessage(role="user", content=[seg] if isinstance(seg, dict) else seg))
            else:
                expanded.append(m)
        elif m.role == "assistant" and m.tool_calls and len(m.tool_calls) > 1:
            _assistant_text = segments_to_text(normalize_content_to_list(m.content))
            if _assistant_text:
                expanded.append(ChatMessage(role="assistant", content=_assistant_text))
            for tc in (m.tool_calls or []):
                expanded.append(ChatMessage(role="assistant", content=None, tool_calls=[tc]))
        else:
            expanded.append(m)

    last_input_tool_id: Optional[str] = None
    last_input_is_tool = False
    for m in reversed(expanded):
        if m.role == "tool" and m.tool_call_id:
            last_input_tool_id = m.tool_call_id
            last_input_is_tool = True
            break
        if m.role == "user":
            break

    tool_results_by_id: Dict[str, ChatMessage] = {}
    assistant_tc_ids: set[str] = set()
    for m in expanded:
        if m.role == "tool" and m.tool_call_id and m.tool_call_id not in tool_results_by_id:
            tool_results_by_id[m.tool_call_id] = m
        if m.role == "assistant" and m.tool_calls:
            try:
                for tc in (m.tool_calls or []):
                    _id = (tc or {}).get("id")
                    if isinstance(_id, str) and _id:
                        assistant_tc_ids.add(_id)
            except Exception:
                pass

    result: List[ChatMessage] = []
    trailing_assistant_msg: Optional[ChatMessage] = None
    for m in expanded:
        if m.role == "tool":
            # Preserve unmatched tool results inline
            if not m.tool_call_id or m.tool_call_id not in assistant_tc_ids:
                result.append(m)
                if m.tool_call_id:
                    tool_results_by_id.pop(m.tool_call_id, None)
            continue
        if m.role == "assistant" and m.tool_calls:
            ids: List[str] = []
            try:
                for tc in (m.tool_calls or []):
                    _id = (tc or {}).get("id")
                    if isinstance(_id, str) and _id:
                        ids.append(_id)
            except Exception:
                pass

            if last_input_is_tool and last_input_tool_id and (last_input_tool_id in ids):
                if trailing_assistant_msg is None:
                    trailing_assistant_msg = m
                continue

            result.append(m)
            for _id in ids:
                tr = tool_results_by_id.pop(_id, None)
                if tr is not None:
                    result.append(tr)
            continue
        result.append(m)

    if last_input_is_tool and last_input_tool_id and trailing_assistant_msg is not None:
        result.append(trailing_assistant_msg)
        tr = tool_results_by_id.pop(last_input_tool_id, None)
        if tr is not None:
            result.append(tr)

    return result 