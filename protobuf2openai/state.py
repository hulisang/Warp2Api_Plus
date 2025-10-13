from __future__ import annotations

import uuid
from typing import Optional
from pydantic import BaseModel
from contextvars import ContextVar


# ==================== 新增部分 ====================
# 这个类用来存储通过 `initialize_once` 预热后获得的全局基线值。
# 这是一个真正的全局单例，只在启动时写入一次。
class GlobalBaselineState(BaseModel):
    conversation_id: Optional[str] = None
    baseline_task_id: Optional[str] = None

# 创建这个全局单例
GLOBAL_BASELINE = GlobalBaselineState()
# ===============================================


class BridgeState(BaseModel):
    conversation_id: Optional[str] = None
    baseline_task_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_message_id: Optional[str] = None


# 使用 ContextVar 来实现请求级别的状态隔离
_state_context: ContextVar[BridgeState] = ContextVar('bridge_state', default=BridgeState())


def get_state() -> BridgeState:
    """获取当前请求的状态"""
    return _state_context.get()


def set_state(state: BridgeState) -> None:
    """设置当前请求的状态"""
    _state_context.set(state)


def ensure_tool_ids():
    """确保工具ID存在"""
    state = get_state()
    if not state.tool_call_id:
        state.tool_call_id = str(uuid.uuid4())
    if not state.tool_message_id:
        state.tool_message_id = str(uuid.uuid4())
    set_state(state)


# 为了向后兼容，保留 STATE 但改为动态属性
class _StateProxy:
    @property
    def conversation_id(self):
        return get_state().conversation_id

    @conversation_id.setter
    def conversation_id(self, value):
        state = get_state()
        state.conversation_id = value
        set_state(state)

    @property
    def baseline_task_id(self):
        return get_state().baseline_task_id

    @baseline_task_id.setter
    def baseline_task_id(self, value):
        state = get_state()
        state.baseline_task_id = value
        set_state(state)

    @property
    def tool_call_id(self):
        return get_state().tool_call_id

    @tool_call_id.setter
    def tool_call_id(self, value):
        state = get_state()
        state.tool_call_id = value
        set_state(state)

    @property
    def tool_message_id(self):
        return get_state().tool_message_id

    @tool_message_id.setter
    def tool_message_id(self, value):
        state = get_state()
        state.tool_message_id = value
        set_state(state)


STATE = _StateProxy()
