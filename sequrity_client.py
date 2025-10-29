"""Sequrity AI client for making API requests to Sequrity endpoints."""

import json
import logging
import requests


# Response classes for OpenAI-compatible format
class Usage:
    """Token usage information."""
    def __init__(self, data):
        self.prompt_tokens = data.get("prompt_tokens", 0)
        self.completion_tokens = data.get("completion_tokens", 0)
        self.total_tokens = data.get("total_tokens", 0)


class ToolCall:
    """Tool call information."""
    def __init__(self, data):
        self.id = data.get("id", "")
        self.type = data.get("type", "function")
        self.function = type('Function', (), {
            'name': data.get("function", {}).get("name", ""),
            'arguments': data.get("function", {}).get("arguments", "{}")
        })()


class Message:
    """Chat message with content unwrapping for Sequrity format."""
    def __init__(self, data):
        self.role = data.get("role", "assistant")
        self.content = self._extract_content(data.get("content", ""))
        self.tool_calls = [ToolCall(tc) for tc in data.get("tool_calls", [])] if data.get("tool_calls") else None

    def _extract_content(self, content):
        """Extract and format content from Sequrity JSON wrapper."""
        # Try to unwrap JSON format: {"final_return_value": {"value": "..."}}
        try:
            parsed = json.loads(content)
            if "final_return_value" in parsed and "value" in parsed["final_return_value"]:
                value = parsed["final_return_value"]["value"]
                return self._format_value(value)
        except (json.JSONDecodeError, TypeError):
            pass

        # Try to handle Python dict string format: "{'Thought': '...', 'Action': '...'}"
        # This happens when PLLM accidentally generates dict instead of plain text
        if content.strip().startswith("{'") or content.strip().startswith('{"'):
            try:
                # Replace single quotes with double quotes for JSON parsing
                json_str = content.strip().replace("'", '"')
                parsed = json.loads(json_str)
                return self._format_value(parsed)
            except (json.JSONDecodeError, ValueError):
                pass

        return content

    def _format_value(self, value):
        """Format the extracted value as expected by the client."""
        if not isinstance(value, dict):
            return str(value)

        # Extract thought and action fields if present (handle both lowercase and capitalized)
        parts = []
        thought = value.get("thought") or value.get("Thought")
        action = value.get("action") or value.get("Action")

        if thought:
            parts.append(f"Thought: {thought}")
        if action:
            parts.append(f"Action: {action}")

        return "\n".join(parts) if parts else str(value)


class Choice:
    """Chat completion choice."""
    def __init__(self, data):
        self.message = Message(data.get("message", {}))
        self.finish_reason = data.get("finish_reason", "stop")
        self.index = data.get("index", 0)


class ChatCompletion:
    """Chat completion response."""
    def __init__(self, data):
        self.id = data.get("id", "")
        self.choices = [Choice(c) for c in data.get("choices", [])]
        self.usage = Usage(data.get("usage", {}))
        self.model = data.get("model", "")
        self.object = data.get("object", "chat.completion")


# Completions interface
class ChatCompletions:
    """Chat completions API interface."""

    def __init__(self, client):
        self.client = client

    def create(self, **kwargs):
        """Create a chat completion."""
        headers = self._build_headers()
        body = self._build_request_body(kwargs)
        self._log_request(body)

        response = self._make_request(headers, body, kwargs.get("timeout", 300))
        response_data = self._unwrap_response(response.json())

        # Extract and conditionally cache session ID based on whether turn is complete
        self._handle_session_id(response, response_data)

        return ChatCompletion(response_data)

    def _build_headers(self):
        """Build request headers including session ID if available."""
        # Minimal policy to enable headers-only mode (required for X-Security-Config to work)
        minimal_policy = {
            "language": "json-sqrt",
            "codes": "[]",  # Empty policy list
            "allow_undefined_tools": True,
            "fail_fast": True,
            "auto_gen": False
        }

        # Minimal features for dual-llm mode
        minimal_features = [
            {
                "feature_name": "Dual LLM",  # Note: must use title case with space
                "config_json": json.dumps({"mode": "standard"})
            }
        ]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.client.api_key}",
            "X-Security-Policy": json.dumps(minimal_policy),
            "X-Security-Features": json.dumps(minimal_features),
            "X-Security-Config": json.dumps({
                "max_nested_session_depth": 2,  # Maximum allowed value (must be < 3)
                "disable_rllm": False,
                "disable_tllm": True
            })
        }

        if not self.client._session_id is None:
            logging.info(f"[Session] Reusing session ID: {self.client._session_id}")
            headers["X-Session-Id"] = self.client._session_id
        else:
            logging.info("[Session] No session ID, starting fresh")

        return headers

    def _build_request_body(self, kwargs):
        """Build request body from parameters."""
        body = {
            "model": kwargs.get("model"),
            "messages": kwargs.get("messages"),
        }

        # Add optional parameters
        for param in ["max_tokens", "seed", "temperature", "timeout", "tools", "tool_choice", "reasoning_effort"]:
            if kwargs.get(param) is not None:
                body[param] = kwargs[param]

        return body

    def _log_request(self, body):
        """Log request details, excluding large image data."""
        msg_count = len(body.get("messages", []))
        has_tools = "tools" in body
        has_images = any(
            isinstance(msg.get("content"), list)
            for msg in body.get("messages", [])
        )

        summary = f"Sending request: model={body.get('model')}, messages={msg_count}"
        if has_tools:
            summary += f", tools={len(body.get('tools', []))}"
        if has_images:
            summary += ", with_images=True"

        logging.info(summary)

    def _make_request(self, headers, body, timeout):
        """Make HTTP POST request to Sequrity endpoint."""
        url = f"{self.client.base_url}/chat/completions"
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout)

            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                logging.error(f"API request failed: {error_msg}")
                raise Exception(error_msg)

            return response

        except requests.exceptions.RequestException as e:
            error_msg = f"Request exception: {str(e)}"
            logging.error(error_msg)
            raise Exception(error_msg)

    def _handle_session_id(self, response, response_data):
        """Handle session ID based on whether the turn is complete or continuing."""
        session_id = response.headers.get("x-session-id") or response.headers.get("X-Session-Id")

        if not session_id:
            logging.warning("[Session] No session ID found in response headers")
            self.client._session_id = None
            return

        # Check if turn is complete (finish_reason="stop") or continuing (tool_calls, etc.)
        finish_reason = None
        if "choices" in response_data and len(response_data["choices"]) > 0:
            finish_reason = response_data["choices"][0].get("finish_reason")

        if finish_reason == "stop":
            # Turn is complete - don't cache session ID for next user turn
            logging.info(f"[Session] Turn complete (finish_reason=stop), not caching session ID {session_id}")
            self.client._session_id = None
        else:
            # Turn is continuing (tool_calls, length, etc.) - cache session ID for continuation
            logging.info(f"[Session] Turn continuing (finish_reason={finish_reason}), caching session ID {session_id}")
            self.client._session_id = session_id

    def _unwrap_response(self, data):
        """Unwrap Sequrity response if needed."""
        if "final_response" in data:
            return data["final_response"]
        return data


# Chat interface
class Chat:
    """Chat API interface."""

    def __init__(self, client):
        self.completions = ChatCompletions(client)


# Main client
class SequrityAI:
    """Client for making requests to Sequrity API endpoints."""

    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self._session_id = None
        self.chat = Chat(self)

    def reset_session(self):
        """Reset session ID for a new task."""
        if self._session_id:
            logging.info(f"[Session] Resetting session ID (was: {self._session_id})")
        self._session_id = None

    def get_pllm_program(self, session_id: str) -> dict:
        """Retrieve the PLLM program for a specific session.

        Args:
            session_id: The session ID to retrieve the program from

        Returns:
            dict with keys:
                - session_id: The session ID
                - program: The PLLM program code (or None if not found)
                - pllm_attempts: Number of PLLM attempts
                - source: "active_session" or "log_file"
        """
        url = f"{self.base_url}/sessions/{session_id}/program"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logging.error(f"Session {session_id} not found or no program available")
                raise Exception(f"Session not found: {response.json().get('detail', 'Unknown error')}")
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                logging.error(f"Failed to retrieve PLLM program: {error_msg}")
                raise Exception(error_msg)

        except requests.exceptions.RequestException as e:
            error_msg = f"Request exception: {str(e)}"
            logging.error(error_msg)
            raise Exception(error_msg)
