from __future__ import annotations

from cyreneAI.core.schema.bot import BotAction, BotEvent


class InMemoryBotChannel:
    """
    内存 bot channel，适合测试和本地开发。
    """

    def __init__(self) -> None:
        self.events: list[BotEvent] = []
        self.actions: list[BotAction] = []

    def push_event(self, event: BotEvent) -> None:
        """
        记录一个待处理事件。
        """
        self.events.append(event)

    def pop_event(self) -> BotEvent | None:
        """
        取出最早的待处理事件。
        """
        if not self.events:
            return None
        return self.events.pop(0)

    async def send(self, action: BotAction) -> None:
        """
        记录 bot 输出动作。
        """
        self.actions.append(action)

    def list_actions(self) -> list[BotAction]:
        """
        列出已发送动作。
        """
        return list(self.actions)

    def clear(self) -> None:
        """
        清空事件和动作。
        """
        self.events.clear()
        self.actions.clear()
