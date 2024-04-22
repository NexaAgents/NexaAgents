import json
from typing import ClassVar, Optional

from autogen.experimental.utils import convert_messages_to_llm_messages

from ..agent import Agent
from ..chat_history import ChatHistoryReadOnly
from ..model_client import ModelClient
from ..termination import NotTerminated, Terminated, Termination, TerminationReason, TerminationResult
from ..types import AssistantMessage, SystemMessage


class ReflectionTerminationManager(Termination):
    SYSTEM_MESSAGE: ClassVar[
        str
    ] = """You are a helpful agent that can look at a conversation and decide if a given goal has been reached by that conversation.
    - If code has been proposed but not yet run then the goal has not been reached.
    - If the code has been run and the output is not as expected then the goal has not been reached.
    - If the code has been run and the output is as expected then the goal has been reached.
    - If the conversation has not yet reached the goal then the agent should continue the conversation.

    You must provide your response as JSON, with two properties:
    - `is_done` (bool): whether the goal has been reached.
    - `reason` (str): the reason for your decision.

    Goal: {goal}
"""

    def __init__(
        self,
        *,
        model_client: ModelClient,
        goal: str,
        system_message: str = SYSTEM_MESSAGE,
        max_turns: Optional[int] = None,
        min_turns: int = 1,
    ) -> None:
        self._model_client = model_client
        self._goal = goal
        self._system_message = system_message
        self._max_turns = max_turns
        self._turns = 0
        self._min_turns = min_turns
        if min_turns < 1:
            raise ValueError("min_turns must be at least 1")
        if max_turns is not None and max_turns < min_turns:
            raise ValueError("max_turns must be greater than or equal to min_turns")

    def record_turn_taken(self, agent: Agent) -> None:
        self._turns += 1

    async def check_termination(self, chat_history: ChatHistoryReadOnly) -> TerminationResult:
        if self._max_turns is not None and self._turns >= self._max_turns:
            return Terminated(TerminationReason.MAX_TURNS_REACHED, "Max turns reached.")

        if self._turns <= self._min_turns:
            return NotTerminated()

        if len(chat_history.messages) == 0:
            return NotTerminated()

        reminder_message = AssistantMessage(
            content=f"Please provide your response as JSON, with two properties: `is_done` (bool) and `reason` (str). Goal: {self._goal}",
            source="system",
        )
        system_message = SystemMessage(content=self._system_message.format(goal=self._goal))
        entire_conversation = (
            [system_message]
            + convert_messages_to_llm_messages(list(chat_history.messages), "reflection")
            + [reminder_message]
        )
        response = await self._model_client.create(entire_conversation)
        try:
            assert isinstance(response.content, str), "tool calls not supported now"
            response_json = json.loads(response.content)
            is_done = response_json.get("is_done", None)
            reason = response_json.get("reason", None)
            if is_done is not None and isinstance(is_done, bool) and reason is not None and isinstance(reason, str):
                if is_done:
                    return Terminated(TerminationReason.GOAL_REACHED, reason)
                return NotTerminated(reason)
            else:
                return NotTerminated(reason)
        except json.JSONDecodeError:
            # TODO: decide what to do in this case
            return NotTerminated("Failed to parse response")

    def reset(self) -> None:
        self._turns = 0
