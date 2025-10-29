"""
Sequrity Computer-Use Agent (CUA) - Multi-turn with client-side vision.

This version:
1. Resets session between turns (new session per screenshot)
2. Performs vision analysis client-side before API call
3. Constructs queries with ultimate goal + current page state
4. Avoids early termination by not using parse_image_with_ai server-side
"""

import argparse
import base64
import json
import logging
import os
import requests
import time
from typing import Any, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from sequrity_client import SequrityAI
from utils import get_web_element_rect


# Tool definitions for web actions (no parse_image_with_ai)
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
            "name": "mark_finished",
            "description": "Mark the task as finished and provide the final answer/result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The final answer or result"
                    }
                },
                "required": ["content"]
            }
        }
    }
]


def analyze_screenshot_with_vision(screenshot_b64: str, web_elements_text: str, vision_api_key: str) -> str:
    """
    Call vision model directly to analyze the screenshot.

    Args:
        screenshot_b64: Base64-encoded screenshot
        web_elements_text: Text describing web elements with labels
        vision_api_key: API key for vision model

    Returns:
        Description of the current page state
    """
    logger = logging.getLogger(__name__)
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {vision_api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "openai/gpt-5",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """Analyze this webpage screenshot and describe what you see.

Provide:
1. What type of page this is
2. What specific content sections or categories are currently visible on screen (mention their names/labels as shown)
3. Key interactive elements visible
4. Available actions

Be specific about section headings and content categories you can see."""
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_b64}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 1000
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        logger.info(f"Vision API response status: {response.status_code}")

        response.raise_for_status()
        data = response.json()

        # Log the raw response for debugging
        logger.debug(f"Vision API response: {json.dumps(data, indent=2)[:1000]}")

        # Debug: Log the message content specifically
        if "choices" in data and len(data["choices"]) > 0:
            msg_content = data["choices"][0].get("message", {}).get("content", "")
            logger.info(f"Vision API content length: {len(msg_content) if msg_content else 0}")
            if msg_content:
                logger.info(f"Vision API content preview: '{msg_content[:200]}'")
            else:
                logger.warning(f"Vision API returned EMPTY content! Full response: {json.dumps(data, indent=2)[:2000]}")

        # Check if response has expected structure
        if "choices" not in data or len(data["choices"]) == 0:
            logger.error(f"Unexpected response structure: {data}")
            # Count elements by counting labels (lines starting with [number]:)
            element_count = len([line for line in web_elements_text.split('\n') if line.strip() and line.strip().startswith('[')])
            return f"Navigation page with {element_count} interactive elements visible"

        content = data["choices"][0]["message"]["content"]

        if not content or content.strip() == "":
            logger.warning("Vision API returned empty content, using fallback")
            element_count = len([line for line in web_elements_text.split('\n') if line.strip() and line.strip().startswith('[')])
            logger.info(f"Fallback: Found {element_count} labeled elements")
            # Provide more context by including some element names
            elements_preview = '; '.join(web_elements_text.split('\n')[:5]) if web_elements_text else ""
            return f"Navigation page with {element_count} elements including: {elements_preview}"

        return content

    except requests.exceptions.HTTPError as e:
        logger.error(f"Vision API HTTP error: {e}, Response: {response.text if response else 'No response'}")
        element_count = len([line for line in web_elements_text.split('\n') if line.strip() and line.strip().startswith('[')])
        return f"Page with {element_count} elements (vision unavailable)"
    except requests.exceptions.Timeout:
        logger.error("Vision API timeout")
        element_count = len([line for line in web_elements_text.split('\n') if line.strip() and line.strip().startswith('[')])
        return f"Page with {element_count} elements (vision timeout)"
    except Exception as e:
        logger.error(f"Vision API error: {type(e).__name__}: {e}")
        element_count = len([line for line in web_elements_text.split('\n') if line.strip() and line.strip().startswith('[')])
        return f"Page with {element_count} elements (vision error)"


class SequrityCUAMultiTurn:
    """Computer-Use Agent with multi-turn session management."""

    def __init__(self, api_key: str, base_url: str, vision_api_key: str, model: str = "gpt-4o"):
        self.client = SequrityAI(api_key=api_key, base_url=base_url)
        self.vision_api_key = vision_api_key
        self.model = model
        self.ultimate_goal = ""
        self.messages = []  # Accumulate full conversation (user→assistant→tool→user...)
        self.logger = logging.getLogger(__name__)

    def set_ultimate_goal(self, goal: str):
        """Set the ultimate goal for the session."""
        self.ultimate_goal = goal

    def get_next_action(self, page_description: str, web_elements_text: str, screenshot_b64: str) -> dict[str, Any] | None:
        """
        Get the next action based on current page state.

        Args:
            page_description: Description of current page from vision analysis
            web_elements_text: Text describing labeled elements
            screenshot_b64: Base64 screenshot (for context)

        Returns:
            dict with keys:
                - tool_name: str
                - arguments: dict
                - reasoning: str
                - tool_call_id: str
            or None if no tool call
        """
        # Reset session for fresh turn (avoids RLLM confusion)
        # But keep self.messages accumulating for conversation context
        self.client.reset_session()

        # Construct query (no need for PREVIOUS ACTIONS - they're in the conversation)
        query = f"""**ULTIMATE GOAL**: {self.ultimate_goal}

**CURRENT PAGE STATE (From analyzing the image)**: {page_description}

**AVAILABLE WEBSITE ELEMENTS**:
{web_elements_text}

**YOUR TASK**:
Determine the NEXT ACTION or the NEXT SERIES of ACTIONS to progress toward the ultimate goal. If the goal is achieved, call mark_finished with the result. Otherwise, use tools to interact with the website to either progress towards the ultimate goal.
"""

        # Append current observation to conversation history
        self.messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": query},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}
                }
            ]
        })

        self.logger.info("Calling Sequrity API with tools...")

        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,  # Use accumulated history
            tools=TOOLS,
            max_tokens=2000,
            timeout=120
        )

        choice = response.choices[0]
        message = choice.message

        # Store assistant response in history
        assistant_msg = {
            "role": "assistant",
            "content": message.content or ""
        }

        # Check if there are tool calls
        if hasattr(message, 'tool_calls') and message.tool_calls:
            tool_call = message.tool_calls[0]

            # Add tool_calls to assistant message
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

        # No tool call
        self.messages.append(assistant_msg)
        self.logger.warning("No tool call in response")
        return None

    def report_tool_result(self, tool_call_id: str, success: bool, message: str = ""):
        """Report the result of a tool execution back to the assistant."""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps({"success": success, "message": message})
        })


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
            for elem_info in labeled_elements:
                if str(elem_info["label"]) == str(label):
                    element = elem_info["element"]
                    # Get current URL before clicking
                    old_url = driver.current_url

                    # Use JavaScript click to bypass any overlays (label overlays can block normal clicks)
                    driver.execute_script("arguments[0].click();", element)

                    # Wait for navigation or dynamic content to load
                    time.sleep(2)

                    # If URL changed, wait a bit more for page to fully load
                    if driver.current_url != old_url:
                        time.sleep(2)

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

        elif tool_name == "mark_finished":
            content = args["content"]
            return True, f"TASK_COMPLETE: {content}"

        else:
            return False, f"Unknown tool: {tool_name}"

    except Exception as e:
        return False, f"Error executing {tool_name}: {str(e)}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, required=True, help="Task description")
    parser.add_argument("--url", type=str, required=True, help="Starting URL")
    parser.add_argument("--model", type=str, default="gpt-4o", help="Model to use")
    parser.add_argument("--max_iterations", type=int, default=15, help="Maximum iterations")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    args = parser.parse_args()

    # Create results directory
    timestamp = time.strftime("%Y%m%d_%H_%M_%S")
    results_dir = os.path.join("results", timestamp)
    task_dir = os.path.join(results_dir, "task_cua_multiturn")
    os.makedirs(task_dir, exist_ok=True)

    # Setup logging
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

    # Get API keys
    api_key = os.getenv("SEQURITY_API_KEY")
    base_url = os.getenv("REMOTE_ENDPOINT")
    vision_api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key or not base_url:
        raise ValueError("SEQURITY_API_KEY and REMOTE_ENDPOINT must be set")
    if not vision_api_key:
        raise ValueError("OPENROUTER_API_KEY must be set for vision analysis")

    # Initialize browser
    options = webdriver.ChromeOptions()
    if args.headless:
        options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)

    # Initialize agent
    agent = SequrityCUAMultiTurn(
        api_key=api_key,
        base_url=base_url,
        vision_api_key=vision_api_key,
        model=args.model
    )
    agent.set_ultimate_goal(args.task)
    logger.info(f"Using model: {args.model}")
    logger.info(f"Ultimate goal: {args.task}")

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

        # Build labeled elements list (0-based to match screenshot labels)
        labeled_elements = []
        for idx, elem in enumerate(web_elements):
            labeled_elements.append({
                "label": str(idx),  # 0-based indexing to match JavaScript labels
                "element": elem
            })

        # Analyze screenshot with vision (client-side)
        logger.info("Analyzing screenshot with vision model...")
        page_description = analyze_screenshot_with_vision(
            screenshot_b64,
            web_text,
            vision_api_key
        )
        logger.info(f"Page description: {page_description}")

        # Get next action
        action = agent.get_next_action(page_description, web_text, screenshot_b64)

        if not action:
            logger.error("No action returned from agent")
            break

        logger.info(f"Action: {action['tool_name']}({action['arguments']})")
        if action['reasoning']:
            logger.info(f"Reasoning: {action['reasoning']}")

        # Check if task is marked as finished
        if action['tool_name'] == "mark_finished":
            logger.info(f"\n{'='*50}\nTASK COMPLETED\n{'='*50}")
            logger.info(action['arguments']['content'])
            break

        # Execute action
        success, message = execute_action(driver, action, labeled_elements)
        logger.info(f"Result: {'✓' if success else '✗'} {message}")

        # Report tool result back to agent (conversation accumulates automatically)
        agent.report_tool_result(action['tool_call_id'], success, message)

        if not success:
            logger.warning("Action failed, agent will retry with different approach")

        # Check if task completed via message
        if "TASK_COMPLETE:" in message:
            logger.info(f"\n{'='*50}\nTASK COMPLETED\n{'='*50}")
            logger.info(message.replace("TASK_COMPLETE: ", ""))
            break

    driver.quit()
    logger.info("Session complete")


if __name__ == "__main__":
    main()
