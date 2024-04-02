import os
import ast
import platform
import json
import logging
import argparse
import shutil
import sqlite3
import aiosqlite
from collections import namedtuple
import functools
from dataclasses import dataclass

from typing import Any, List, Dict, Optional, Type, cast, Set, Callable

from textual import on
from textual import work
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.containers import ScrollableContainer, Grid, Container, Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    Markdown,
    Static,
    Input,
    DirectoryTree,
    Label,
    Switch,
    Collapsible,
    LoadingIndicator,
    Button,
    TabbedContent,
    ListView,
    ListItem,
    TextArea,
)
from textual.reactive import reactive
from textual.message import Message

import autogen
from autogen import config_list_from_json  # type: ignore[import-untyped]
from autogen import Agent, AssistantAgent, UserProxyAgent, ConversableAgent  # type: ignore[import-untyped], ConversableAgent
from autogen.coding import LocalCommandLineCodeExecutor
from autogen.coding.func_with_reqs import FunctionWithRequirements

from .tools import Tool, InvalidToolError
from .exceptions import ChatMessageError, ToolUpdateError, SubprocessError
from .app_config import AppConfiguration


APP_CONFIG = AppConfiguration()
APP_CONFIG.initialize()
# do not save the LLM config to the database, keep it in memory
LLM_CONFIG = {
    "config_list": config_list_from_json("OAI_CONFIG_LIST"),
}
logging.basicConfig(
    level=logging.INFO,
    filename=os.path.join(APP_CONFIG.get_data_path(), "app.log"),
    filemode="w",
    format="%(asctime)-15s %(message)s",
)


def fetch_chat_history(root_id: int = 0) -> List[Dict[str, str]]:
    """
    Fetch the chat history from the database.

    Args:
        root_id: the root id of the messages to fetch. If None, all messages are fetched.

    Returns:
        A list of chat messages.
    """
    conn = sqlite3.connect(APP_CONFIG.get_database_path())
    c = conn.cursor()
    c.execute("SELECT root_id, id, role, content FROM chat_history WHERE root_id = ?", (root_id,))
    chat_history = [
        {"root_id": root_id, "id": id, "role": role, "content": content} for root_id, id, role, content in c.fetchall()
    ]
    conn.close()
    return chat_history


async def a_fetch_chat_history(root_id: int = 0) -> List[Dict[str, str]]:
    """
    Fetch the chat history from the database.

    Args:
        root_id: the root id of the messages to fetch. If None, all messages are fetched.

    Returns:
        A list of chat messages.
    """
    async with aiosqlite.connect(APP_CONFIG.get_database_path()) as conn:
        c = await conn.cursor()
        await c.execute("SELECT root_id, id, role, content FROM chat_history WHERE root_id = ?", (root_id,))
        chat_history = [
            {"root_id": root_id, "id": id, "role": role, "content": content}
            for root_id, id, role, content in await c.fetchall()
        ]
        return chat_history


def fetch_row(id: int, root_id: int = 0) -> Optional[Dict[str, str]]:
    """
    Fetch a single row from the database.

    Args:
        id: the id of the row to fetch
        root_id: the root id of the row to fetch. If not specified, it's assumed to be 0.

    Returns:
        A single row from the database.
    """
    conn = sqlite3.connect(APP_CONFIG.get_database_path())
    c = conn.cursor()
    c.execute("SELECT role, content FROM chat_history WHERE id = ? AND root_id = ?", (id, root_id))
    row = [{"role": role, "content": content, "id": id, "root_id": root_id} for role, content in c.fetchall()]
    conn.close()
    return row[0] if row else None


async def a_fetch_row(id: int, root_id: int = 0) -> Optional[Dict[str, str]]:
    """
    Fetch a single row from the database.

    Args:
        id: the id of the row to fetch
        root_id: the root id of the row to fetch. If not specified, it's assumed to be 0.

    Returns:
        A single row from the database.
    """
    async with aiosqlite.connect(APP_CONFIG.get_database_path()) as conn:
        c = await conn.cursor()
        await c.execute("SELECT role, content FROM chat_history WHERE id = ? AND root_id = ?", (id, root_id))
        row = [{"role": role, "content": content, "id": id, "root_id": root_id} for role, content in await c.fetchall()]
        return row[0] if row else None


def insert_chat_message(role: str, content: str, root_id: int, id: Optional[int] = None) -> int:
    """
    Insert a chat message into the database.

    Args:
        role: the role of the message
        content: the content of the message
        root_id: the root id of the message
        id: the id of the row to update. If None, a new row is inserted.

    Returns:
        The id of the inserted (or modified) row.
    """
    try:
        with sqlite3.connect(APP_CONFIG.get_database_path()) as conn:
            c = conn.cursor()
            if id is None:
                c.execute("SELECT MAX(id) FROM chat_history WHERE root_id = ?", (root_id,))
                max_id = c.fetchone()[0]
                id = max_id + 1 if max_id is not None else 0
                data_a = (root_id, id, role, content)
                c.execute("INSERT INTO chat_history (root_id, id, role, content) VALUES (?, ?, ?, ?)", data_a)
                conn.commit()
                return id
            else:
                c.execute("SELECT * FROM chat_history WHERE root_id = ? AND id = ?", (root_id, id))
                if c.fetchone() is None:
                    data_b = (root_id, id, role, content)
                    c.execute("INSERT INTO chat_history (root_id, id, role, content) VALUES (?, ?, ?, ?)", data_b)
                    conn.commit()
                    return id
                else:
                    data_c = (role, content, root_id, id)
                    c.execute("UPDATE chat_history SET role = ?, content = ? WHERE root_id = ? AND id = ?", data_c)
                    conn.commit()
                    return id
    except sqlite3.Error as e:
        raise ChatMessageError(f"Error inserting or updating chat message: {e}")


async def a_insert_chat_message(role: str, content: str, root_id: int, id: Optional[int] = None) -> int:
    """
    Insert a chat message into the database.

    Args:
        role: the role of the message
        content: the content of the message
        root_id: the root id of the message
        id: the id of the row to update. If None, a new row is inserted.

    Returns:
        The id of the inserted (or modified) row.
    """
    try:
        async with aiosqlite.connect(APP_CONFIG.get_database_path()) as conn:
            c = await conn.cursor()
            if id is None:
                await c.execute("SELECT MAX(id) FROM chat_history WHERE root_id = ?", (root_id,))
                item = await c.fetchone()
                max_id = None
                if item is not None:
                    max_id = item[0]
                id = max_id + 1 if max_id is not None else 0
                data_a = (root_id, id, role, content)
                await c.execute("INSERT INTO chat_history (root_id, id, role, content) VALUES (?, ?, ?, ?)", data_a)
                await conn.commit()
                return id
            else:
                await c.execute("SELECT * FROM chat_history WHERE root_id = ? AND id = ?", (root_id, id))
                if await c.fetchone() is None:
                    data_b = (root_id, id, role, content)
                    await c.execute("INSERT INTO chat_history (root_id, id, role, content) VALUES (?, ?, ?, ?)", data_b)
                    await conn.commit()
                    return id
                else:
                    data_c = (role, content, root_id, id)
                    await c.execute(
                        "UPDATE chat_history SET role = ?, content = ? WHERE root_id = ? AND id = ?", data_c
                    )
                    await conn.commit()
                    return id
    except aiosqlite.Error as e:
        raise ChatMessageError(f"Error inserting or updating chat message: {e}")


def message2markdown(message) -> str:
    """
    Convert a message to markdown that can be displayed in the chat display.

    Args:
        message: a message

    Returns:
        A markdown string.
    """
    role = message.role
    if role == "user":
        display_name = APP_CONFIG.get_user_name()
    elif role == "assistant":
        display_name = "TinyRA"
    else:
        display_name = "\U0001F4AD" * 3

    display_id = message.id

    content = message.content

    return f"[{display_id}] {display_name}: {content}"


MessageData = namedtuple("MessageData", ["role", "content", "id"])


class ReactiveMessage(Markdown):
    """
    A reactive markdown widget for displaying assistant messages.
    """

    # message = reactive({"role": None, "content": None, "id": None})
    message = reactive(MessageData(None, None, None))

    class Selected(Message):
        """Assistant message selected message."""

        def __init__(self, msg_id: str) -> None:
            self.msg_id = msg_id
            super().__init__()

    def __init__(self, id=None, role=None, content=None, **kwargs):
        super().__init__(**kwargs)
        # self.message = {"role": role, "content": content, "id": id}
        self.message = MessageData(role, content, id)

    def on_mount(self) -> None:
        self.set_interval(1, self.update_message)
        chat_display = self.app.query_one(ChatDisplay)
        chat_display.scroll_end()

    def on_click(self) -> None:
        self.post_message(self.Selected(self.message.id))

    async def update_message(self):
        message = await a_fetch_row(self.message.id)

        if message is None:
            self.remove()
            return

        message = MessageData(message["role"], message["content"], message["id"])

        self.classes = f"{message.role.lower()}-message message"

        self.message = message

    async def watch_message(self) -> str:
        return await self.update(message2markdown(self.message))


def message_display_handler(message: Dict[str, str]):
    """
    Given a message, return a widget for displaying the message.
    If the message is from the user, return a markdown widget.
    If the message is from the assistant, return a reactive markdown widget.

    Args:
        message: a message

    Returns:
        A markdown widget or a reactive markdown widget.
    """
    role = message["role"]
    id = message["id"]
    content = message["content"]
    message_widget = ReactiveMessage(id=id, role=role, content=content, classes=f"{role.lower()}-message message")
    return message_widget


class DirectoryTreeContainer(ScrollableContainer):
    """
    A container for displaying the directory tree.
    """

    dirpath = APP_CONFIG.get_workdir()
    dir_contents = reactive(str(os.listdir(APP_CONFIG.get_workdir())))

    def compose(self) -> ComposeResult:
        yield DirectoryTree(self.dirpath)

    def on_mount(self) -> None:
        self.set_interval(1, self.update_dir_contents)

    def update_dir_contents(self) -> None:
        self.dir_contents = str(os.listdir(self.dirpath))

    def watch_dir_contents(self):
        self.query_one(DirectoryTree).reload()

    def on_tree_node_highlighted(self, event: DirectoryTree.NodeHighlighted) -> None:
        logging.info(f"Highlighted {event.node}")
        self.highlighted_node = event.node


class ChatDisplay(ScrollableContainer):
    """
    A container for displaying the chat history.

    When a new message is detected, it is mounted to the container.
    """

    limit_history = 100

    # num_messages = reactive(len(fetch_chat_history()))

    # async def watch_num_messages(self) -> None:
    # self.scroll_end()

    def compose(self) -> ComposeResult:
        chat_history = fetch_chat_history()
        for message in chat_history[-self.limit_history :]:
            widget = message_display_handler(message)
            yield widget


class ChatInput(Input):
    """
    A widget for user input.
    """

    def on_mount(self) -> None:
        self.focus()


class QuitScreen(ModalScreen):
    """Screen with a dialog to quit."""

    BINDINGS = [("escape", "app.pop_screen", "Pop screen")]

    def compose(self) -> ComposeResult:
        yield Grid(
            Static("Are you sure you want to quit?", id="question"),
            Grid(
                Button("Quit", variant="error", id="quit"),
                Button("Cancel", variant="primary", id="cancel"),
                id="quit-screen-footer",
            ),
            id="quit-screen-grid",
        )

    @on(Button.Pressed, "#quit")
    def quit(self) -> None:
        self.app.exit()

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.app.pop_screen()


class NotificationScreen(ModalScreen):
    """Screen with a dialog to display notifications."""

    BINDINGS = [("escape", "app.pop_screen", "Pop screen")]

    def __init__(self, *args, message: Optional[str] = None, **kwargs):
        self.message = message or ""
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        with Grid(id="notification-screen-grid"):
            yield Static(self.message, id="notification")

            with Grid(id="notification-screen-footer"):
                yield Button("Dismiss", variant="primary", id="dismiss-notification")

    @on(Button.Pressed, "#dismiss-notification")
    def dismiss(self, result: Any) -> None:  # type: ignore[override]
        self.app.pop_screen()


class Title(Static):
    pass


class OptionGroup(Container):
    pass


class DarkSwitch(Horizontal):
    def compose(self) -> ComposeResult:
        yield Switch(value=self.app.dark)
        yield Static("Dark mode toggle", classes="label")

    def on_mount(self) -> None:
        self.watch(self.app, "dark", self.on_dark_change, init=False)

    def on_dark_change(self) -> None:
        self.query_one(Switch).value = self.app.dark

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self.app.dark = event.value


class CustomMessage(Static):
    pass


class Sidebar(Container):
    def compose(self) -> ComposeResult:
        yield Title("Work Directory")
        with Grid(id="directory-tree-grid"):
            yield DirectoryTreeContainer(id="directory-tree")
            with Grid(id="directory-tree-footer"):
                yield Button("Delete", variant="error", id="delete-file-button")
                yield Button("Empty Work Dir", variant="error", id="empty-work-dir-button")


class CloseScreen(Message):

    def __init__(self, screen_id: str) -> None:
        self.screen_id = screen_id
        super().__init__()


class HistoryTab(Grid):

    len_history = reactive(0, recompose=True)
    num_tools = reactive(0, recompose=True)

    def update_history(self) -> None:
        self.len_history = len(fetch_chat_history())

    def update_tools(self) -> None:
        self.num_tools = len(APP_CONFIG.get_tools())

    def on_mount(self) -> None:
        self.set_interval(1, self.update_history)
        self.set_interval(1, self.update_tools)

    def compose(self) -> ComposeResult:
        with Container(id="history-contents"):
            yield Markdown(f"## Number of messages: {self.len_history}\n\n## Number of tools: {self.num_tools}")
        with Container(id="history-footer", classes="settings-screen-footer"):
            yield Button("Clear History", variant="error", id="clear-history-button")

    @on(Button.Pressed, "#clear-history-button")
    def clear_history(self) -> None:
        APP_CONFIG.clear_chat_history()

        self.screen.close_settings()


class UserSettingsTab(Grid):

    def compose(self) -> ComposeResult:
        self.widget_user_name = Input(APP_CONFIG.get_user_name())
        self.widget_user_bio = TextArea(APP_CONFIG.get_user_bio(), id="user-bio")
        self.widget_user_preferences = TextArea(APP_CONFIG.get_user_preferences(), id="user-preferences")

        with Grid(id="user-settings-contents"):
            yield Container(Label("Name", classes="form-label"), self.widget_user_name)
            with TabbedContent("Bio", "Preferences"):
                yield self.widget_user_bio
                yield self.widget_user_preferences

        with Horizontal(classes="settings-screen-footer"):
            yield Button("Save", variant="primary", id="save-user-settings")

    @on(Button.Pressed, "#save-user-settings")
    def save_user_settings(self) -> None:
        new_user_name = self.widget_user_name.value
        new_user_bio = self.widget_user_bio.text
        new_user_preferences = self.widget_user_preferences.text

        APP_CONFIG.update_configuration(
            user_name=new_user_name, user_bio=new_user_bio, user_preferences=new_user_preferences
        )

        self.screen.close_settings()


class ToolSettingsTab(Grid):

    def compose(self) -> ComposeResult:
        tools = APP_CONFIG.get_tools()
        # list of tools
        with Container(id="tool-list-container"):
            yield ListView(
                *(ListItem(Label(tools[tool_id].name), id=f"tool-{tool_id}") for tool_id in tools),
                id="tool-list",
            )
            yield Button("+", variant="primary", id="new-tool-button")

        # display the settings for the selected tool
        with Grid(id="tool-view-grid"):

            with Vertical():
                yield Label("Tool ID", classes="form-label")
                yield Input(id="tool-id-input", disabled=True)

            with Vertical():
                yield Label("Tool Name (Display)", classes="form-label")
                yield Input(id="tool-name-input")

            # code editor for the selected tool
            with Horizontal(id="tool-code-container"):
                # yield Label("Code", classes="form-label")
                yield TextArea.code_editor("", language="python", id="tool-code-textarea")

            # footer for the tool view
            with Horizontal(id="tool-view-footer-grid"):
                yield Button("Save", variant="primary", id="save-tool-settings")
                yield Button("Delete", variant="error", id="delete-tool-button")

    @on(Button.Pressed, "#new-tool-button")
    def create_new_tool(self) -> None:
        tools = APP_CONFIG.get_tools()

        new_id = max(tools.keys()) + 1 if tools else 1

        new_tool_name = f"tool-{new_id}"

        tool = Tool(new_tool_name, id=new_id)

        try:
            tool.validate_tool()
        except InvalidToolError as e:
            error_message = f"{e}"
            self.post_message(AppErrorMessage(error_message))
            return

        try:
            APP_CONFIG.update_tool(tool)
        except ToolUpdateError as e:
            error_message = f"{e}"
            self.post_message(AppErrorMessage(error_message))
            return

        list_view_widget = self.query_one("#tool-list", ListView)
        new_list_item = ListItem(Label(new_tool_name), id=f"tool-{new_id}")

        list_view_widget.append(new_list_item)
        num_items = len(list_view_widget)
        list_view_widget.index = num_items - 1
        list_view_widget.action_select_cursor()

    @on(Button.Pressed, "#delete-tool-button")
    def delete_tool(self) -> None:
        # get the id of the selected tool
        tool_id_str = self.query_one("#tool-id-input", Input).value
        # check if its a valid int
        try:
            tool_id = int(tool_id_str)
        except ValueError:
            error_message = "Tool ID must be an integer"
            self.post_message(AppErrorMessage(error_message))
            return

        # tool_id = int(self.query_one("#tool-id-input", Input).value)
        item = self.query_one(f"#tool-{tool_id}", ListItem)
        # delete the tool from the database
        try:
            APP_CONFIG.delete_tool(tool_id)
        except ToolUpdateError as e:
            error_message = f"{e}"
            self.post_message(AppErrorMessage(error_message))
            return

        # remove the tool from the list view
        item.remove()

        list_view_widget = self.query_one("#tool-list", ListView)

        if len(list_view_widget) > 0:
            list_view_widget.action_cursor_up()
            list_view_widget.action_select_cursor()
        else:
            self.query_one("#tool-code-textarea", TextArea).text = ""
            self.query_one("#tool-name-input", Input).value = ""
            self.query_one("#tool-id-input", Input).value = ""

    @on(Button.Pressed, "#save-tool-settings")
    def save_tool_settings(self) -> None:
        # get the id of the selected tool
        tool_id = int(self.query_one("#tool-id-input", Input).value)
        tool_name = self.query_one("#tool-name-input", Input).value
        tool_code = self.query_one("#tool-code-textarea", TextArea).text

        tool = Tool(tool_name, tool_code, id=tool_id)

        try:
            tool.validate_tool()
        except InvalidToolError as e:
            error_message = f"{e}"
            self.post_message(AppErrorMessage(error_message))
            return

        try:
            APP_CONFIG.update_tool(tool)
        except ToolUpdateError as e:
            error_message = f"{e}"
            self.post_message(AppErrorMessage(error_message))
            return

        item_label = self.query_one(f"#tool-{tool_id} > Label", Label)
        item_label.update(tool_name)
        self.screen.close_settings()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        tool_id = int(event.item.id[5:])
        tool = APP_CONFIG.get_tools(tool_id)[tool_id]
        if tool:
            self.query_one("#tool-code-textarea", TextArea).text = tool.code
            self.query_one("#tool-name-input", Input).value = tool.name
            self.query_one("#tool-id-input", Input).value = str(tool_id)
        else:
            self.app.post_message(AppErrorMessage("Tool not found"))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        list_view_widget = self.query_one("#tool-list", ListView)
        # check if a item is already selected in the list view

        if len(list_view_widget) == 0:
            return

        elif list_view_widget.highlighted_child is None:
            list_view_widget.index = 0
            list_view_widget.action_select_cursor()

        elif list_view_widget.highlighted_child is not None:
            list_view_widget.action_select_cursor()


class SettingsScreen(ModalScreen):
    """Screen with a dialog to display settings."""

    BINDINGS = [("escape", "app.pop_screen", "Dismiss")]

    def compose(self) -> ComposeResult:

        with TabbedContent("User", "Tools", "History", id="settings-screen"):
            # Tab for user settings
            yield UserSettingsTab(id="user-settings")

            # Tab for tools settings
            yield ToolSettingsTab(id="tools-tab-grid")

            # Tab for history settings
            yield HistoryTab(id="history-settings")

    def close_settings(self) -> None:
        self.app.pop_screen()


@dataclass
class AgentMessage:

    role: str
    content: str

    def __str__(self):
        return f"{self.role}:\n{self.content}"


@dataclass
class State:

    name: str
    description: str
    tags: List[str]

    def __str__(self):
        return f"{self.name}"

    def __eq__(self, other):
        if isinstance(other, State):
            return self.name == other.name and self.description == other.description and self.tags == other.tags
        return False

    def __hash__(self):
        return hash((self.name, self.description, tuple(self.tags)))


@dataclass
class StateSpace:

    states: Set[State]

    def __str__(self):
        return " ".join([str(state) for state in self.states])

    def filter_states(self, condition: Callable[State, bool]) -> "StateSpace":
        filtered_states = {state for state in self.states if condition(state)}
        return StateSpace(filtered_states)


@dataclass
class MessageProfile:

    message: AgentMessage
    cost: float
    duration: float
    states: Set[State]  # unorddered collection of states

    def __str__(self):
        repr = f"Cost: {self.cost}\tDuration: {self.duration}\t"
        for state in self.states:
            repr += str(state) + " "
        return repr


class AppErrorMessage(Message):
    """An error message for the app."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__()


class Profiler:

    DEFAULT_STATE_SPACE = StateSpace(
        states={
            State(
                name="USER-REQUEST",
                description="The message shows the *user* requesting a task that needs to be completed",
                tags=["user"],
            ),
            State(
                name="CODING",
                description="The message shows the assistant writing python or shell code to solve a problem. IE the message contains code blocks. This code does not apply to markdown code blocks",
                tags=["assistant"],
            ),
            State(
                name="PLANNING",
                description="The message shows that the agent is create a step by step plan to accomplish some task.",
                tags=["assistant"],
            ),
            State(
                name="ANALYSING-RESULTS",
                description="The assistant's message is reflecting on results obtained so far",
                tags=["assistant"],
            ),
            State(
                name="CODE-EXECUTION",
                description="The user shared results of code execution, e.g., results, logs, error trace",
                tags=["user"],
            ),
            State(
                name="CODE-EXECUTION-ERROR",
                description="The user shared results of code execution and they show an error in execution",
                tags=["user"],
            ),
            State(
                name="CODE-EXECUTION-SUCCESS",
                description="The user shared results of code execution and they show a successful execution",
                tags=["user"],
            ),
            State(
                name="CODING-TOOL-USE",
                description="The message contains a code block and the code uses method from the `functions` module eg indicated by presence of `from functions import....`",
                tags=["assistant"],
            ),
            State(
                name="ASKING-FOR-INFO",
                description="The assistant is asking a question",
                tags=["assistant"],
            ),
            State(
                name="SUMMARIZING",
                description="The assistant is synthesizing/summarizing information gathered so far",
                tags=["assistant"],
            ),
            State(
                name="TERMINATE", description="The agent's message contains the word 'TERMINATE'", tags=["assistant"]
            ),
            State(name="EMPTY", description="The message is empty", tags=["user"]),
            State(
                name="UNDEFINED",
                description="Use this code when the message does not fit any of the other codes",
                tags=["user", "assistant"],
            ),
        }
    )

    def __init__(self, state_space: StateSpace = None):
        self.state_space = state_space or self.DEFAULT_STATE_SPACE

    def profile_message(self, message: AgentMessage) -> MessageProfile:

        def role_in_tags(state: State) -> bool:
            # if state has no tags, the state applies to all roles
            if state.tags is None:
                return True
            return message.role in state.tags

        state_space = self.state_space.filter_states(condition=role_in_tags)
        state_space_str = ""

        for state in state_space.states:
            state_space_str += f"{state.name}: {state.description}" + "\n"

        prompt = f"""Which of the following codes apply to the message:
List of codes:
{state_space_str}

Message
    role: "{message.role}"
    content: "{message.content}"

Only respond with codes that apply. Codes should be separated by commas.
    """
        client = autogen.OpenAIWrapper(**LLM_CONFIG)
        response = client.create(messages=[{"role": "user", "content": prompt}])
        response = client.extract_text_or_completion_object(response)[0]

        extracted_states_names = response.split(",")
        extracted_states = []
        for state_name in extracted_states_names:
            extracted_states.append(State(name=state_name, description="", tags=[]))

        message_profile = MessageProfile(cost=0.0, duration=0.0, states=extracted_states, message=message)

        return message_profile


@dataclass
class ChatProfile:

    num_messages: int
    message_profiles: List[MessageProfile]  # ordered collection of message profiles

    def __str__(self):
        repr = f"Num messages: {self.num_messages}" + "\n"
        for message_profile in self.message_profiles:
            repr += str(message_profile) + "\n"
        return repr


class ProfileNode(Static):

    message_profile: MessageProfile

    DEFAULT_CSS = """
    ProfileNode Markdown {
        border: solid $primary;
        padding: 1;
    }
"""

    def compose(self) -> ComposeResult:
        states = self.message_profile.states

        def state_name_comparator(x: State, y: State):
            return x.name < y.name

        states.sort(key=functools.cmp_to_key(state_name_comparator))

        state_display_str = " ".join([str(state) for state in states])

        with Collapsible(collapsed=True, title=state_display_str):
            yield Static(str(self.message_profile))
            yield Markdown(str(self.message_profile.message))


class ProfileDiagram(ScrollableContainer):

    chat_profile: ChatProfile = reactive(None, recompose=True)

    def compose(self) -> ComposeResult:

        if self.chat_profile is None:
            yield Label("Profiling...")
            yield LoadingIndicator()
            return

        # if self.chat_profile.num_messages == 0:
        #     yield LoadingIndicator()
        #     return
        num_messages = self.chat_profile.num_messages
        yield Label(f"Number of messages: {num_messages}", classes="heading")
        for message_profile in self.chat_profile.message_profiles:
            node = ProfileNode()
            node.message_profile = message_profile
            yield node


class ProfilerContainer(Container):

    root_id = None
    chat_history = reactive(None)
    profile_diagram = None

    def on_mount(self) -> None:
        # self.update_chat_history()
        # self.start_profiling()
        self.set_interval(1, self.update_chat_history)

    def update_chat_history(self) -> None:
        self.chat_history = fetch_chat_history(self.root_id)

    def watch_chat_history(self, new_chat_history) -> None:
        if new_chat_history is None:
            return

        self.start_profiling()

    @work(thread=True, exclusive=True)
    async def start_profiling(self):
        chat_profile = await self.profile_chat()
        if self.profile_diagram is None:
            self.profile_diagram = ProfileDiagram()
        self.profile_diagram.chat_profile = chat_profile

    async def profile_chat(self) -> ChatProfile:
        profiler = Profiler()
        message_profile_list = []
        for message in self.chat_history:
            _message = AgentMessage(role=message["role"], content=message["content"])
            msg_profile = profiler.profile_message(_message)
            message_profile_list.append(msg_profile)

        chat_profile = ChatProfile(num_messages=len(self.chat_history), message_profiles=message_profile_list)

        return chat_profile

    def compose(self):
        if self.profile_diagram is None:
            self.profile_diagram = ProfileDiagram()
        yield self.profile_diagram


class ChatScreen(ModalScreen):
    """A screen that displays a chat history"""

    root_msg_id = 0
    BINDINGS = [("escape", "app.pop_screen", "Pop screen")]

    def compose(self) -> ComposeResult:
        history = fetch_chat_history(self.root_msg_id)
        with Grid(id="chat-screen"):

            with Container(id="chat-screen-header"):
                yield Label(f"Monitoring 🧵 Thread: {self.root_msg_id}", classes="heading")

            with TabbedContent("Overview", "Details", id="chat-screen-tabs"):
                profiler = ProfilerContainer(id="chat-profiler")
                profiler.root_id = self.root_msg_id
                profiler.chat_history = history

                yield profiler

                with ScrollableContainer(id="chat-screen-contents"):
                    for msg in history:
                        if msg["role"] == "assistant":
                            msg_class = "assistant-message"
                        if msg["role"] == "user":
                            msg_class = "user-message"
                        yield Markdown(f"{msg['role']}:\n{msg['content']}", classes=msg_class + " message")

            with Horizontal(id="chat-screen-footer"):
                yield Button("Learn New Tool", variant="error", id="learn")

    @on(Button.Pressed, "#learn")
    def learn(self) -> None:
        learning_screen = LearningScreen()
        learning_screen.root_msg_id = self.root_msg_id
        self.app.push_screen(learning_screen)


class LearningScreen(ModalScreen):

    BINDINGS = [("escape", "app.pop_screen", "Pop screen")]

    root_msg_id = None

    def compose(self) -> ComposeResult:
        with Grid(id="learning-screen"):
            yield Horizontal(Label("Interactive Tool Learning", classes="heading"), id="learning-screen-header")
            yield ScrollableContainer(
                TextArea.code_editor(
                    f"""
                    # Learning a function for {self.root_msg_id}
                    """,
                    language="python",
                ),
                id="learning-screen-contents",
            )
            with Horizontal(id="learning-screen-footer"):
                # yield Button("Start", variant="error", id="start-learning")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        self.start_learning()

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        widget = self.query_one("#learning-screen-contents > TextArea", TextArea)
        code = widget.text
        name = code.split("\n")[0][1:]

        tool = Tool(name, code)
        try:
            tool.validate_tool()
            APP_CONFIG.update_tool(tool)
            self.app.pop_screen()
            self.app.push_screen(NotificationScreen(message="Tool saved successfully"))

        except InvalidToolError as e:
            error_message = f"{e}"
            self.post_message(AppErrorMessage(error_message))
            return

        except ToolUpdateError as e:
            error_message = f"{e}"
            self.post_message(AppErrorMessage(error_message))
            return

    @work(thread=True)
    async def start_learning(self) -> None:
        widget = self.query_one("#learning-screen-contents > TextArea", TextArea)
        widget.text = "# Learning..."

        history = await a_fetch_chat_history(self.root_msg_id)
        name, code = learn_tool_from_history(history)

        widget.text = "#" + name + "\n" + code


def learn_tool_from_history(history: List[Dict[str, str]]) -> str:

    # return "hola"

    markdown = ""
    for msg in history:
        markdown += f"{msg['role']}: {msg['content']}\n"

    agent = ConversableAgent(
        "learning_assistant",
        llm_config=LLM_CONFIG,
        system_message="""You are a helpful assistant that for the given chat
history can return a standalone, documented python function.

Try to extract a most general version of the function based on the chat history.
That can be reused in the future for similar tasks. Eg do not use hardcoded arguments.
Instead make them function parameters.

The chat history contains a task the agents were trying to accomplish.
Analyze the following chat history to assess if the task was completed,
and if it was return the python function that would accomplish the task.
        """,
    )
    messages = [
        {
            "role": "user",
            "content": f"""The chat history is

            {markdown}

            Only generate a single python function in code blocks and nothing else.
            Make sure all imports are inside the function.
            Both ast.FunctionDef, ast.AsyncFunctionDef are acceptable.

            Function signature should be annotated properly.
            Function should return a string as the final result.
            """,
        }
    ]
    reply = agent.generate_reply(messages)
    from autogen.code_utils import extract_code

    # extract a code block from the reply
    code_blocks = extract_code(reply)
    lang, code = code_blocks[0]

    messages.append({"role": "assistant", "content": code})

    messages.append(
        {
            "role": "user",
            "content": """suggest a max two word english phrase that is a friendly
          display name for the function. Only reply with the name in a code block.
          no need to use an quotes or code blocks. Just two words.""",
        }
    )

    name = agent.generate_reply(messages)

    return name, code


def generate_response_process(msg_idx: int):
    chat_history = fetch_chat_history()
    task = chat_history[msg_idx]["content"]

    def terminate_on_consecutive_empty(recipient, messages, sender, **kwargs):
        # check the contents of the last N messages
        # if all empty, terminate
        consecutive_are_empty = None
        last_n = 2

        for message in reversed(messages):
            if last_n == 0:
                break
            if message["role"] == "user":
                last_n -= 1
                if len(message["content"]) == 0:
                    consecutive_are_empty = True
                else:
                    consecutive_are_empty = False
                    break

        if consecutive_are_empty:
            return True, "TERMINATE"

        return False, None

    def summarize(text):
        return text[:100]

    def post_snippet_and_record_history(sender, message, recipient, silent):
        if silent is True:
            return message

        if isinstance(message, str):
            summary = message
            insert_chat_message(sender.name, message, root_id=msg_idx + 1)
        elif isinstance(message, Dict):
            if message.get("content"):
                summary = message["content"]
                insert_chat_message(sender.name, message["content"], root_id=msg_idx + 1)
            elif message.get("tool_calls"):
                tool_calls = message["tool_calls"]
                summary = "Calling tools…"
                insert_chat_message(sender.name, json.dumps(tool_calls), root_id=msg_idx + 1)
            else:
                raise ValueError("Message must have a content or tool_calls key")

        snippet = summarize(summary)
        insert_chat_message("info", snippet, root_id=0, id=msg_idx + 1)
        return message

    tools = APP_CONFIG.get_tools()

    functions = []
    for tool in tools.values():
        func = FunctionWithRequirements.from_str(tool.code)
        functions.append(func)
    executor = LocalCommandLineCodeExecutor(work_dir=APP_CONFIG.get_workdir(), functions=functions)

    system_message = APP_CONFIG.get_assistant_system_message()
    system_message += executor.format_functions_for_prompt()

    assistant = AssistantAgent(
        "assistant",
        llm_config=LLM_CONFIG,
        system_message=system_message,
    )
    user = UserProxyAgent(
        "user",
        code_execution_config={"executor": executor},
        human_input_mode="NEVER",
        is_termination_msg=lambda x: x.get("content") and "TERMINATE" in x.get("content", ""),
    )

    # populate the history before registering new reply functions
    for msg in chat_history:
        if msg["role"] == "user":
            user.send(msg["content"], assistant, request_reply=False, silent=True)
        else:
            assistant.send(msg["content"], user, request_reply=False, silent=True)

    assistant.register_reply([Agent, None], terminate_on_consecutive_empty)
    assistant.register_hook("process_message_before_send", post_snippet_and_record_history)
    user.register_hook("process_message_before_send", post_snippet_and_record_history)

    logging.info("Current history:")
    logging.info(assistant.chat_messages[user])

    # hack to get around autogen's current api...
    initial_reply = assistant.generate_reply(None, user)
    assistant.initiate_chat(user, message=initial_reply, clear_history=False, silent=False)

    # user.send(task, assistant, request_reply=True, silent=False)

    user.send(
        f"""Based on the results in above conversation, create a response for the user.
While computing the response, remember that this conversation was your inner mono-logue. The user does not need to know every detail of the conversation.
All they want to see is the appropriate result for their task (repeated below) in a manner that would be most useful.
The task was: {task}

There is no need to use the word TERMINATE in this response.
        """,
        assistant,
        request_reply=False,
        silent=True,
    )
    response = assistant.generate_reply(assistant.chat_messages[user], user)
    assistant.send(response, user, request_reply=False, silent=True)

    response = assistant.chat_messages[user][-1]["content"]

    insert_chat_message("assistant", response, root_id=0, id=msg_idx + 1)


class TinyRA(App):
    """
    Main application for TinyRA.
    """

    BINDINGS = [
        ("ctrl+b", "toggle_sidebar", "Work Directory"),
        ("ctrl+c", "request_quit", "Quit"),
        ("ctrl+s", "request_settings", "Settings"),
    ]

    CSS_PATH = "tui.css"

    TITLE = "TinyRA"
    SUB_TITLE = "A minimalistic, long-lived research assistant"

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""

        yield Header(show_clock=True)

        yield Sidebar(classes="-hidden", id="sidebar")

        with Grid(id="chat-grid"):
            yield ChatDisplay(id="chat-history")
            yield ChatInput(id="chat-input-box")

        yield Footer()

    def action_request_quit(self) -> None:
        self.push_screen(QuitScreen())

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

    def action_request_settings(self) -> None:
        self.push_screen(SettingsScreen())

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one(Sidebar)
        if sidebar.has_class("-hidden"):
            sidebar.remove_class("-hidden")
        else:
            sidebar.add_class("-hidden")

    @on(AppErrorMessage)
    def notify_error_to_user(self, event: AppErrorMessage) -> None:
        self.push_screen(NotificationScreen(message=event.message))

    @on(Button.Pressed, "#empty-work-dir-button")
    def empty_work_dir(self, event: Button.Pressed) -> None:
        work_dir = APP_CONFIG.get_workdir()
        for file in os.listdir(work_dir):
            file_path = os.path.join(work_dir, file)
            if os.path.isfile(file_path):
                os.remove(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)

    @on(Button.Pressed, "#delete-file-button")
    def delete_file(self, event: Button.Pressed) -> None:
        dir_tree = self.query_one("#directory-tree > DirectoryTree", DirectoryTree)
        highlighted_node = dir_tree.cursor_node

        if highlighted_node is not None:
            dir_tree.action_cursor_up()
            if highlighted_node.data is not None:
                file_path = str(highlighted_node.data.path)
                APP_CONFIG.delete_file_or_dir(file_path)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Called when the user click a file in the directory tree."""
        event.stop()
        try:
            # open the file using the default app
            logging.info(f"Opening file '{event.path}'")
            # check if the app is running in a codespace
            if os.environ.get("CODESPACES"):
                os.system(f"code '{event.path}'")
            else:
                # open the file using the default app
                os.system(f"open '{event.path}'")
        except Exception:
            # TODO: Not implemented
            pass
        else:
            # TODO: Not implemented
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = self.query_one("#chat-input-box", Input).value.strip()
        self.query_one(Input).value = ""
        self.handle_input(user_input)

    def on_reactive_message_selected(self, event: ReactiveMessage.Selected) -> None:
        """Called when a reactive assistant message is selected."""
        new_chat_screen = ChatScreen()
        new_chat_screen.root_msg_id = int(event.msg_id)
        self.push_screen(new_chat_screen)

    @work()
    async def handle_input(self, user_input: str) -> None:
        chat_display_widget = self.query_one(ChatDisplay)

        # display the user input in the chat display
        id = await a_insert_chat_message("user", user_input, root_id=0)
        user_message = await a_fetch_row(id)
        if user_message is None:
            # TODO - what to do if the message is not found?
            return
        reactive_message = message_display_handler(user_message)
        await chat_display_widget.mount(reactive_message)

        # display the assistant response in the chat display
        assistant_message = {
            "role": "info",
            "content": "Computing response…",
            "id": str(id + 1),
        }
        await a_insert_chat_message("info", "Computing response…", root_id=0, id=id + 1)
        reactive_message = message_display_handler(assistant_message)
        await chat_display_widget.mount(reactive_message)

        try:
            # await run_in_subprocess(generate_response_process, id)
            self.generate_response(id)
        except SubprocessError as e:
            error_message = f"{e}"
            await a_insert_chat_message("error", error_message, root_id=0, id=id + 1)
            self.post_message(AppErrorMessage(error_message))
            # raise e

    @work(thread=True)
    def generate_response(self, msg_idx: int) -> None:
        generate_response_process(msg_idx)


def run_app() -> None:
    """
    Run the TinyRA app.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Reset chat history")
    parser.add_argument("--reset-all", action="store_true", help="Reset chat history and delete data path")
    args = parser.parse_args()

    if args.reset_all:
        print(f"Warning: Resetting chat history and deleting data path {APP_CONFIG.get_data_path()}")
        print("Press enter to continue or Ctrl+C to cancel.")
        input()
        if os.path.exists(APP_CONFIG.get_database_path()):
            os.remove(APP_CONFIG.get_database_path())
        if os.path.exists(APP_CONFIG.get_data_path()):
            shutil.rmtree(APP_CONFIG.get_data_path())
        exit()

    if args.reset:
        print(f"Warning: Resetting chat history. This will delete all chat history in {APP_CONFIG.get_database_path()}")
        print("Press enter to continue or Ctrl+C to cancel.")
        input()
        if os.path.exists(APP_CONFIG.get_database_path()):
            os.remove(APP_CONFIG.get_database_path())
        exit()

    app = TinyRA()
    app.run()


if __name__ == "__main__":
    run_app()
