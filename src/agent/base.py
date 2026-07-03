"""Agent 抽象接口。

解耦具体实现，方便未来切换模型生态。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generator

from .schemas import AgentEvent


class BaseAgent(ABC):
    """Agent 抽象基类。

    所有 Agent 实现必须继承此类，
    实现 run() 方法返回事件生成器。
    """

    @abstractmethod
    def run(self, query: str, lang: str = "zh") -> Generator[AgentEvent, None, None]:
        """执行 Agent 推理，逐事件 yield。

        事件类型：thinking / tool_call / tool_result / answer_chunk / error / usage / done
        """
        ...
        yield  # type: ignore
