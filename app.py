import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
import websockets
from rich.markdown import Markdown
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)


def parse_headers(raw: str) -> Dict[str, str]:
    """Parse a block of header lines into a dictionary."""
    headers: Dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"Invalid header line (missing colon): {line}")
        key, value = line.split(":", 1)
        headers[key.strip()] = value.strip()
    return headers


class StatusIndicator(Static):
    """Simple status bar for transient messages."""

    status: reactive[str] = reactive("Ready")

    def watch_status(self, status: str) -> None:
        self.update(f"[b]{status}")


@dataclass
class RestResponse:
    status_code: int
    reason_phrase: str
    elapsed: float
    headers: Dict[str, str]
    body: str


class ResponseDisplay(Static):
    """Render HTTP responses with headings."""

    def update_with_response(self, response: RestResponse) -> None:
        markdown = Markdown(
            f"### {response.status_code} {response.reason_phrase}\n"
            f"- Time: {response.elapsed:.2f} ms\n"
            f"- Headers:\n"
            + "\n".join([f"    - **{k}**: {v}" for k, v in response.headers.items()])
            + "\n"
            "### Body\n\n"
            f"```\n{response.body}\n```"
        )
        self.update(markdown)

    def update_with_error(self, error: str) -> None:
        self.update(Markdown(f"### Error\n\n```\n{error}\n```"))


class RequestWorkbenchApp(App):
    """A lightweight API workbench supporting REST, GraphQL, and WebSocket flows."""

    CSS_PATH = "app.tcss"
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    _ws_connection: Optional[websockets.WebSocketClientProtocol]
    _ws_receiver: Optional[asyncio.Task]

    def __init__(self) -> None:
        super().__init__()
        self._ws_connection = None
        self._ws_receiver = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusIndicator(id="status")
        with TabbedContent("REST", "GraphQL", "WebSocket", id="main-tabs"):
            with TabPane("REST"):
                yield self._rest_content()
            with TabPane("GraphQL"):
                yield self._graphql_content()
            with TabPane("WebSocket"):
                yield self._websocket_content()
        yield Footer()

    def _rest_content(self) -> Horizontal:
        return Horizontal(
            Vertical(
                Label("HTTP Method"),
                Select(
                    options=[
                        ("GET", "GET"),
                        ("POST", "POST"),
                        ("PUT", "PUT"),
                        ("PATCH", "PATCH"),
                        ("DELETE", "DELETE"),
                        ("HEAD", "HEAD"),
                        ("OPTIONS", "OPTIONS"),
                    ],
                    value="GET",
                    id="rest_method",
                ),
                Label("Request URL"),
                Input(placeholder="https://api.example.com/resource", id="rest_url"),
                Label("Headers (one per line, key: value)"),
                TextArea(placeholder="Authorization: Bearer ...", id="rest_headers"),
                Label("Body"),
                TextArea(
                    placeholder='{"name": "Nocturne"}',
                    id="rest_body",
                    show_line_numbers=True,
                ),
                Button("Send Request", id="rest_send", variant="success"),
                id="rest_form",
                classes="panel",
            ),
            Vertical(
                Label("Response"),
                ResponseDisplay(id="rest_response"),
                id="rest_output",
                classes="panel",
            ),
            id="rest_layout",
        )

    def _graphql_content(self) -> Horizontal:
        return Horizontal(
            Vertical(
                Label("Endpoint URL"),
                Input(placeholder="https://example.com", id="graphql_url"),
                Label("Headers"),
                TextArea(placeholder="Authorization: Bearer ...", id="graphql_headers"),
                Label("Query"),
                TextArea(
                    placeholder="query Example { launchesPast(limit: 2) { mission_name } }",
                    id="graphql_query",
                    show_line_numbers=True,
                ),
                Label("Variables (JSON)"),
                TextArea(placeholder='{"limit": 2}', id="graphql_variables", show_line_numbers=True),
                Button("Run Query", id="graphql_send", variant="success"),
                id="graphql_form",
                classes="panel",
            ),
            Vertical(
                Label("Response"),
                ResponseDisplay(id="graphql_response"),
                id="graphql_output",
                classes="panel",
            ),
            id="graphql_layout",
        )

    def _websocket_content(self) -> Horizontal:
        return Horizontal(
            Vertical(
                Label("Socket URL"),
                Input(placeholder="wss://echo.websocket.org", id="ws_url"),
                Label("Headers"),
                TextArea(placeholder="Authorization: Bearer ...", id="ws_headers"),
                Horizontal(
                    Button("Connect", id="ws_connect", variant="primary"),
                    Button("Disconnect", id="ws_disconnect", variant="warning"),
                    id="ws_buttons",
                ),
                Label("Message"),
                TextArea(placeholder="Type a message to send...", id="ws_message"),
                Button("Send Message", id="ws_send", variant="success"),
                id="ws_controls",
                classes="panel",
            ),
            Vertical(
                Label("Activity"),
                RichLog(id="ws_log", markup=True, wrap=True),
                id="ws_output",
                classes="panel",
            ),
            id="ws_layout",
        )

    async def _send_rest_request(self) -> None:
        status = self.query_one(StatusIndicator)
        method = self.query_one("#rest_method", Select).value
        url = self.query_one("#rest_url", Input).value.strip()
        headers_raw = self.query_one("#rest_headers", TextArea).text
        body = self.query_one("#rest_body", TextArea).text
        response_display = self.query_one("#rest_response", ResponseDisplay)

        if not url:
            response_display.update_with_error("Please provide a request URL.")
            return

        try:
            headers = parse_headers(headers_raw)
        except ValueError as error:
            response_display.update_with_error(str(error))
            return

        status.status = f"Sending {method} {url}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, headers=headers or None, content=body or None)
        except Exception as error:
            status.status = "Request failed"
            response_display.update_with_error(str(error))
            return

        status.status = f"Received {response.status_code} in {response.elapsed.total_seconds() * 1000:.2f} ms"
        rest_response = RestResponse(
            status_code=response.status_code,
            reason_phrase=response.reason_phrase,
            elapsed=response.elapsed.total_seconds() * 1000,
            headers=dict(response.headers),
            body=response.text,
        )
        response_display.update_with_response(rest_response)

    async def _send_graphql_request(self) -> None:
        status = self.query_one(StatusIndicator)
        url = self.query_one("#graphql_url", Input).value.strip()
        query = self.query_one("#graphql_query", TextArea).text.strip()
        headers_raw = self.query_one("#graphql_headers", TextArea).text
        variables_raw = self.query_one("#graphql_variables", TextArea).text
        response_display = self.query_one("#graphql_response", ResponseDisplay)

        if not url:
            response_display.update_with_error("Please provide an endpoint URL.")
            return
        if not query:
            response_display.update_with_error("GraphQL query is required.")
            return

        try:
            headers = parse_headers(headers_raw)
        except ValueError as error:
            response_display.update_with_error(str(error))
            return

        variables: Optional[Dict[str, Any]]
        if variables_raw.strip():
            try:
                variables = json.loads(variables_raw)
            except json.JSONDecodeError as error:
                response_display.update_with_error(f"Variables must be valid JSON: {error}")
                return
        else:
            variables = None

        payload = {"query": query}
        if variables is not None:
            payload["variables"] = variables

        status.status = f"Posting GraphQL query to {url}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers or None, json=payload)
        except Exception as error:
            status.status = "GraphQL request failed"
            response_display.update_with_error(str(error))
            return

        status.status = f"GraphQL {response.status_code}"
        graph_response = RestResponse(
            status_code=response.status_code,
            reason_phrase=response.reason_phrase,
            elapsed=response.elapsed.total_seconds() * 1000,
            headers=dict(response.headers),
            body=response.text,
        )
        response_display.update_with_response(graph_response)

    async def _connect_websocket(self) -> None:
        status = self.query_one(StatusIndicator)
        url = self.query_one("#ws_url", Input).value.strip()
        headers_raw = self.query_one("#ws_headers", TextArea).text
        log_widget = self.query_one("#ws_log", RichLog)

        if not url:
            log_widget.write("Please provide a WebSocket URL.")
            return

        if self._ws_connection is not None:
            log_widget.write("Already connected. Disconnect first.")
            return

        try:
            headers = parse_headers(headers_raw)
        except ValueError as error:
            log_widget.write(f"[red]Header error:[/red] {error}")
            return

        status.status = f"Connecting to {url}"
        log_widget.clear()
        try:
            self._ws_connection = await websockets.connect(url, additional_headers=headers or None)
        except Exception as error:
            status.status = "WebSocket connection failed"
            log_widget.write(f"[red]Connection error:[/red] {error}")
            self._ws_connection = None
            return

        status.status = "WebSocket connected"
        log_widget.write(f"[green]Connected to {url}[/green]")
        self._ws_receiver = asyncio.create_task(self._receive_websocket_messages())

    async def _receive_websocket_messages(self) -> None:
        log_widget = self.query_one("#ws_log", RichLog)
        assert self._ws_connection is not None
        try:
            async for message in self._ws_connection:
                log_widget.write(f"[cyan]<-[/cyan] {message}")
        except websockets.exceptions.ConnectionClosed as closed:
            log_widget.write(f"[yellow]Connection closed ({closed.code})[/yellow]")
        except Exception as error:
            log_widget.write(f"[red]Receiver error:[/red] {error}")
        finally:
            self._ws_connection = None
            self._ws_receiver = None
            self.query_one(StatusIndicator).status = "WebSocket disconnected"

    async def _disconnect_websocket(self) -> None:
        if self._ws_connection is None:
            self.query_one("#ws_log", RichLog).write("No active connection.")
            return

        try:
            await self._ws_connection.close()
        finally:
            self._ws_connection = None
            if self._ws_receiver:
                self._ws_receiver.cancel()
            self.query_one(StatusIndicator).status = "WebSocket disconnected"
            self.query_one("#ws_log", RichLog).write("[yellow]Disconnected[/yellow]")

    async def _send_websocket_message(self) -> None:
        message = self.query_one("#ws_message", TextArea).text
        log_widget = self.query_one("#ws_log", RichLog)

        if self._ws_connection is None:
            log_widget.write("Connect before sending messages.")
            return
        if not message:
            log_widget.write("Message is empty.")
            return

        try:
            await self._ws_connection.send(message)
            log_widget.write(f"[magenta]->[/magenta] {message}")
        except Exception as error:
            log_widget.write(f"[red]Send error:[/red] {error}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "rest_send":
            await self._send_rest_request()
        elif button_id == "graphql_send":
            await self._send_graphql_request()
        elif button_id == "ws_connect":
            await self._connect_websocket()
        elif button_id == "ws_disconnect":
            await self._disconnect_websocket()
        elif button_id == "ws_send":
            await self._send_websocket_message()

    async def on_unmount(self) -> None:
        if self._ws_connection is not None:
            await self._disconnect_websocket()


def main() -> None:
    """Entry point for console script."""
    RequestWorkbenchApp().run()


if __name__ == "__main__":
    main()
