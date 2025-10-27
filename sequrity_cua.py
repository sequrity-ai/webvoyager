"""
Sequrity Computer-Use Agent (CUA) - Tool-based web automation.

This module implements a cleaner architecture where web actions (Click, Scroll, Type, etc.)
are exposed as native tools instead of generating Python code.
"""

import argparse
import base64
import json
import logging
import os
import time
from typing import Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from sequrity_client import SequrityAI
from utils import get_web_element_rect


# Tool definitions for web actions
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "click_element",
            "description": "Click on a web element identified by its numerical label",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "The numerical label of the element to click (e.g., '5', '14')"
                    }
                },
                "required": ["label"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type content into a textbox element. The system will automatically press ENTER after typing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "The numerical label of the textbox element"
                    },
                    "content": {
                        "type": "string",
                        "description": "The text content to type into the textbox"
                    }
                },
                "required": ["label", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scroll_page",
            "description": "Scroll up or down on the webpage. Can scroll the entire window or a specific element area.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Either 'WINDOW' to scroll the entire page, or a numerical label to scroll within a specific element area"
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "The direction to scroll"
                    }
                },
                "required": ["target", "direction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Wait for 5 seconds. Typically used to wait for unfinished webpage processes.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "go_back",
            "description": "Go back to the previous webpage in browser history.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "google_search",
            "description": "Jump directly to the Google search page. Use when you can't find information on the current website.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "answer",
            "description": "Provide the final answer when all questions in the task have been solved.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The final answer content"
                    }
                },
                "required": ["content"]
            }
        }
    }
]


SYSTEM_PROMPT = """Web automation task: Complete the user's goal by analyzing webpage screenshots.

Screenshots show numerical labels in the TOP LEFT corner of interactive elements. Use functionalities that can help to understand image contents to identify which element labels to interact with.

Notes:
- Numerical labels identify clickable elements, textboxes, etc.
- If an action doesn't work, try a different approach (e.g., scroll to reveal more content)
- Complete one action per iteration
"""


class SequrityCUA:
    """Computer-Use Agent using Sequrity's tool-based architecture."""

    def __init__(self, api_key: str, base_url: str, model: str = "gpt-4o"):
        self.client = SequrityAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.messages = []
        self.logger = logging.getLogger(__name__)

    def add_system_prompt(self):
        """Add system prompt with tool usage instructions."""
        self.messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT
        })

    def add_observation(self, screenshot_b64: str, web_elements_text: str):
        """Add a new observation (screenshot + element text) to the conversation."""
        observation_text = (
            f"Observation: Analyze the screenshot to determine the next action.\n\n"
            f"Web elements (label: text content):\n{web_elements_text}\n\n"
            f"Use parse_image_with_ai to analyze the screenshot and identify which element to interact with."
        )

        self.messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": observation_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}
                }
            ]
        })

    def get_next_action(self) -> dict[str, Any] | None:
        """
        Call Sequrity API with tools and get the next action.

        Returns:
            dict with keys:
                - tool_name: str (e.g., "click_element")
                - arguments: dict (e.g., {"label": "5"})
                - reasoning: str (the assistant's reasoning)
            or None if no tool call was made
        """
        self.logger.info("Calling Sequrity API with tools...")

        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            tools=TOOLS,
            max_tokens=2000,
            timeout=120
        )

        # Get assistant message
        choice = response.choices[0]
        message = choice.message

        # Store assistant message
        assistant_msg = {
            "role": "assistant",
            "content": message.content or ""
        }

        # Check if there are tool calls
        if hasattr(message, 'tool_calls') and message.tool_calls:
            tool_call = message.tool_calls[0]  # Get first tool call
            # Convert ToolCall object to dict for JSON serialization
            assistant_msg["tool_calls"] = [{
                "id": tool_call.id,
                "type": tool_call.type,
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments
                }
            }]

            self.messages.append(assistant_msg)

            return {
                "tool_name": tool_call.function.name,
                "arguments": json.loads(tool_call.function.arguments),
                "reasoning": message.content or "",
                "tool_call_id": tool_call.id
            }

        # No tool call - just reasoning
        self.messages.append(assistant_msg)
        self.logger.warning("No tool call in response, only reasoning")
        return None

    def report_tool_result(self, tool_call_id: str, success: bool, message: str = ""):
        """Report the result of a tool execution back to the assistant."""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps({"success": success, "message": message})
        })

    def reset_session(self):
        """Reset session for a new task."""
        self.client.reset_session()
        self.messages = []


def execute_action(driver: webdriver.Chrome, action: dict, labeled_elements: list) -> tuple[bool, str]:
    """
    Execute a web action based on the tool call.

    Returns:
        (success, message) tuple
    """
    tool_name = action["tool_name"]
    args = action["arguments"]

    try:
        if tool_name == "click_element":
            label = args["label"]
            # Find element with this label
            for elem_info in labeled_elements:
                if str(elem_info["label"]) == str(label):
                    element = elem_info["element"]
                    element.click()
                    time.sleep(1)
                    return True, f"Clicked element [{label}]"
            return False, f"Element with label [{label}] not found"

        elif tool_name == "type_text":
            label = args["label"]
            content = args["content"]
            for elem_info in labeled_elements:
                if str(elem_info["label"]) == str(label):
                    element = elem_info["element"]
                    element.clear()
                    element.send_keys(content)
                    element.send_keys(Keys.RETURN)
                    time.sleep(1)
                    return True, f"Typed '{content}' into element [{label}]"
            return False, f"Element with label [{label}] not found"

        elif tool_name == "scroll_page":
            target = args["target"]
            direction = args["direction"]
            scroll_amount = 500 if direction == "down" else -500

            if target.upper() == "WINDOW":
                driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            else:
                # Scroll specific element
                for elem_info in labeled_elements:
                    if str(elem_info["label"]) == str(target):
                        element = elem_info["element"]
                        driver.execute_script(f"arguments[0].scrollTop += {scroll_amount};", element)
                        break
            time.sleep(1)
            return True, f"Scrolled {direction}"

        elif tool_name == "wait":
            time.sleep(5)
            return True, "Waited 5 seconds"

        elif tool_name == "go_back":
            driver.back()
            time.sleep(2)
            return True, "Went back to previous page"

        elif tool_name == "google_search":
            driver.get("https://www.google.com")
            time.sleep(2)
            return True, "Navigated to Google"

        elif tool_name == "answer":
            content = args["content"]
            return True, f"Task complete. Answer: {content}"

        else:
            return False, f"Unknown tool: {tool_name}"

    except Exception as e:
        return False, f"Error executing {tool_name}: {str(e)}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, required=True, help="Task description")
    parser.add_argument("--url", type=str, required=True, help="Starting URL")
    parser.add_argument("--model", type=str, default="gpt-4o", help="Model to use (must support vision and tools)")
    parser.add_argument("--max_iterations", type=int, default=15, help="Maximum iterations")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    args = parser.parse_args()

    # Create results directory
    timestamp = time.strftime("%Y%m%d_%H_%M_%S")
    results_dir = os.path.join("results", timestamp)
    task_dir = os.path.join(results_dir, "task_cua")
    os.makedirs(task_dir, exist_ok=True)

    # Setup logging to both console and file
    log_file = os.path.join(task_dir, 'agent.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)

    api_key = os.getenv("SEQURITY_API_KEY")
    base_url = os.getenv("REMOTE_ENDPOINT")

    if not api_key or not base_url:
        raise ValueError("SEQURITY_API_KEY and REMOTE_ENDPOINT must be set")

    # Initialize browser
    options = webdriver.ChromeOptions()
    if args.headless:
        options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)

    # Initialize agent
    agent = SequrityCUA(api_key=api_key, base_url=base_url, model=args.model)
    # Don't add system prompt - let PLLM handle everything
    # agent.add_system_prompt()
    logger.info(f"Using model: {args.model}")

    # Add initial task
    agent.messages.append({
        "role": "user",
        "content": f"Task: {args.task}\n\nPlease navigate to {args.url} and complete the task."
    })

    # Navigate to starting URL
    driver.get(args.url)
    time.sleep(3)

    # Main loop
    for iteration in range(args.max_iterations):
        logger.info(f"\n{'='*50}\nIteration {iteration + 1}\n{'='*50}")

        # Draw labels on page FIRST
        rects, web_elements, web_text = get_web_element_rect(driver, fix_color=True)

        # THEN capture screenshot with labels visible
        screenshot_path = os.path.join(task_dir, f'screenshot{iteration + 1}.png')
        driver.save_screenshot(screenshot_path)

        with open(screenshot_path, 'rb') as f:
            screenshot_b64 = base64.b64encode(f.read()).decode('utf-8')

        # Build labeled elements list
        labeled_elements = []
        for idx, elem in enumerate(web_elements):
            labeled_elements.append({
                "label": str(idx + 1),
                "element": elem
            })

        # Add observation
        agent.add_observation(screenshot_b64, web_text)

        # Get next action
        action = agent.get_next_action()

        if not action:
            logger.error("No action returned from agent")
            break

        logger.info(f"Action: {action['tool_name']}({action['arguments']})")
        if action['reasoning']:
            logger.info(f"Reasoning: {action['reasoning']}")

        # Check if this is the answer
        if action['tool_name'] == "answer":
            logger.info(f"\n{'='*50}\nFINAL ANSWER\n{'='*50}")
            logger.info(action['arguments']['content'])
            agent.report_tool_result(action['tool_call_id'], True, "Task completed")
            break

        # Execute action
        success, message = execute_action(driver, action, labeled_elements)
        logger.info(f"Result: {'✓' if success else '✗'} {message}")

        # Report result
        agent.report_tool_result(action['tool_call_id'], success, message)

        if not success:
            logger.warning("Action failed, agent will retry with different approach")

    driver.quit()
    logger.info("Session complete")


if __name__ == "__main__":
    main()
