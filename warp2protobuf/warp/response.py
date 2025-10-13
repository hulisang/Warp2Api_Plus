#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Warp API response parsing

Handles parsing of protobuf responses and extraction of OpenAI-compatible content.
"""
from typing import Optional, Dict, List, Any

from ..core.logging import logger
from ..core.protobuf import ensure_proto_runtime, msg_cls


def extract_openai_content_from_response(payload: bytes) -> dict:
    """
    Extract OpenAI-compatible content from Warp API response payload.
    """
    if not payload:
        logger.debug("extract_openai_content_from_response: payload is empty")
        return {"content": None, "tool_calls": [], "finish_reason": None, "metadata": {}}

    logger.debug(f"extract_openai_content_from_response: processing payload of {len(payload)} bytes")

    hex_dump = payload.hex()
    logger.debug(f"extract_openai_content_from_response: complete payload hex: {hex_dump}")

    try:
        ensure_proto_runtime()
        ResponseEvent = msg_cls("warp.multi_agent.v1.ResponseEvent")
        response = ResponseEvent()
        response.ParseFromString(payload)

        result = {"content": "", "tool_calls": [], "finish_reason": None, "metadata": {}}

        if response.HasField("client_actions"):
            for i, action in enumerate(response.client_actions.actions):
                if action.HasField("append_to_message_content"):
                    message = action.append_to_message_content.message
                    if message.HasField("agent_output"):
                        agent_output = message.agent_output
                        if agent_output.text:
                            result["content"] += agent_output.text
                        if agent_output.reasoning:
                            if "reasoning" not in result:
                                result["reasoning"] = ""
                            result["reasoning"] += agent_output.reasoning
                    if message.HasField("tool_call"):
                        tool_call = message.tool_call
                        openai_tool_call = {
                            "id": getattr(tool_call, 'id', f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": getattr(tool_call, 'name', getattr(tool_call, 'function_name', 'unknown')),
                                "arguments": getattr(tool_call, 'arguments', getattr(tool_call, 'parameters', '{}'))
                            }
                        }
                        result["tool_calls"].append(openai_tool_call)
                elif action.HasField("add_messages_to_task"):
                    for j, msg in enumerate(action.add_messages_to_task.messages):
                        if msg.HasField("agent_output") and msg.agent_output.text:
                            result["content"] += msg.agent_output.text
                        if msg.HasField("tool_call"):
                            tool_call = msg.tool_call
                            tool_name = "unknown"
                            tool_args = "{}"
                            tool_call_id = getattr(tool_call, 'tool_call_id', f"call_{i}_{j}")
                            for field, value in tool_call.ListFields():
                                if field.name == 'tool_call_id':
                                    continue
                                tool_name = field.name
                                if hasattr(value, 'ListFields'):
                                    tool_fields_dict = {}
                                    for tool_field, tool_value in value.ListFields():
                                        if isinstance(tool_value, str):
                                            tool_fields_dict[tool_field.name] = tool_value
                                        elif hasattr(tool_value, '__len__') and not isinstance(tool_value, str):
                                            tool_fields_dict[tool_field.name] = list(tool_value)
                                        else:
                                            tool_fields_dict[tool_field.name] = str(tool_value)
                                    if tool_fields_dict:
                                        import json
                                        tool_args = json.dumps(tool_fields_dict)
                                break
                            openai_tool_call = {
                                "id": tool_call_id,
                                "type": "function",
                                "function": {"name": tool_name, "arguments": tool_args}
                            }
                            result["tool_calls"].append(openai_tool_call)
                elif action.HasField("update_task_message"):
                    umsg = action.update_task_message.message
                    if umsg.HasField("agent_output") and umsg.agent_output.text:
                        result["content"] += umsg.agent_output.text
                elif action.HasField("create_task"):
                    task = action.create_task.task
                    for j, msg in enumerate(task.messages):
                        if msg.HasField("agent_output") and msg.agent_output.text:
                            result["content"] += msg.agent_output.text
                elif action.HasField("update_task_summary"):
                    summary = action.update_task_summary.summary
                    if summary:
                        result["content"] += summary
        if response.HasField("finished"):
            result["finish_reason"] = "stop"
        result["metadata"] = {
            "response_fields": [field.name for field, _ in response.ListFields()],
            "has_client_actions": response.HasField("client_actions"),
            "payload_size": len(payload)
        }
        return result
    except Exception as e:
        logger.error(f"extract_openai_content_from_response: exception occurred: {e}")
        import traceback
        logger.error(f"extract_openai_content_from_response: traceback: {traceback.format_exc()}")
        return {"content": None, "tool_calls": [], "finish_reason": "error", "metadata": {"error": str(e)}}


def extract_text_from_response(payload: bytes) -> Optional[str]:
    result = extract_openai_content_from_response(payload)
    return result["content"] if result["content"] else None


def extract_openai_sse_deltas_from_response(payload: bytes) -> List[Dict[str, Any]]:
    if not payload:
        return []
    try:
        ensure_proto_runtime()
        ResponseEvent = msg_cls("warp.multi_agent.v1.ResponseEvent")
        response = ResponseEvent()
        response.ParseFromString(payload)
        deltas = []
        if response.HasField("client_actions"):
            for i, action in enumerate(response.client_actions.actions):
                if action.HasField("append_to_message_content"):
                    message = action.append_to_message_content.message
                    if message.HasField("agent_output"):
                        agent_output = message.agent_output
                        if agent_output.text:
                            deltas.append({"choices": [{"index": 0, "delta": {"content": agent_output.text}, "finish_reason": None}]})
                        if agent_output.reasoning:
                            deltas.append({"choices": [{"index": 0, "delta": {"reasoning": agent_output.reasoning}, "finish_reason": None}]})
                    if message.HasField("tool_call"):
                        tool_call = message.tool_call
                        deltas.append({"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
                        openai_tool_call = {
                            "id": getattr(tool_call, 'tool_call_id', f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": getattr(tool_call, 'name', 'unknown'),
                                "arguments": getattr(tool_call, 'arguments', '{}')
                            }
                        }
                        deltas.append({"choices": [{"index": 0, "delta": {"tool_calls": [openai_tool_call]}, "finish_reason": None}]})
                elif action.HasField("add_messages_to_task"):
                    for j, msg in enumerate(action.add_messages_to_task.messages):
                        if msg.HasField("agent_output") and msg.agent_output.text:
                            deltas.append({"choices": [{"index": 0, "delta": {"content": msg.agent_output.text}, "finish_reason": None}]})
                        if msg.HasField("tool_call"):
                            tool_call = msg.tool_call
                            if j == 0:
                                deltas.append({"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
                            tool_call_id = getattr(tool_call, 'tool_call_id', f"call_{i}_{j}")
                            tool_name = "unknown"
                            tool_args = "{}"
                            for field, value in tool_call.ListFields():
                                if field.name == 'tool_call_id':
                                    continue
                                tool_name = field.name
                                if hasattr(value, 'ListFields'):
                                    tool_fields_dict = {}
                                    for tool_field, tool_value in value.ListFields():
                                        if isinstance(tool_value, str):
                                            tool_fields_dict[tool_field.name] = tool_value
                                        elif hasattr(tool_value, '__len__') and not isinstance(tool_value, str):
                                            tool_fields_dict[tool_field.name] = list(tool_value)
                                        else:
                                            tool_fields_dict[tool_field.name] = str(tool_value)
                                    if tool_fields_dict:
                                        import json
                                        tool_args = json.dumps(tool_fields_dict)
                                break
                            openai_tool_call = {"id": tool_call_id, "type": "function", "function": {"name": tool_name, "arguments": tool_args}}
                            deltas.append({"choices": [{"index": 0, "delta": {"tool_calls": [openai_tool_call]}, "finish_reason": None}]})
                elif action.HasField("update_task_message"):
                    umsg = action.update_task_message.message
                    if umsg.HasField("agent_output") and umsg.agent_output.text:
                        deltas.append({"choices": [{"index": 0, "delta": {"content": umsg.agent_output.text}, "finish_reason": None}]})
                elif action.HasField("create_task"):
                    task = action.create_task.task
                    for j, msg in enumerate(task.messages):
                        if msg.HasField("agent_output") and msg.agent_output.text:
                            deltas.append({"choices": [{"index": 0, "delta": {"content": msg.agent_output.text}, "finish_reason": None}]})
                elif action.HasField("update_task_summary"):
                    summary = action.update_task_summary.summary
                    if summary:
                        deltas.append({"choices": [{"index": 0, "delta": {"content": summary}, "finish_reason": None}]})
        if response.HasField("finished"):
            deltas.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        return deltas
    except Exception as e:
        logger.error(f"extract_openai_sse_deltas_from_response: exception occurred: {e}")
        import traceback
        logger.error(f"extract_openai_sse_deltas_from_response: traceback: {traceback.format_exc()}")
        return []