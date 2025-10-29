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
import platform
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
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "Whether the click action succeeded"
                    },
                    "message": {
                        "type": "string",
                        "description": "Status message describing the result"
                    }
                },
                "required": ["success", "message"]
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
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "Whether the typing action succeeded"
                    },
                    "message": {
                        "type": "string",
                        "description": "Status message describing the result"
                    }
                },
                "required": ["success", "message"]
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
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "Whether the scroll action succeeded"
                    },
                    "message": {
                        "type": "string",
                        "description": "Status message describing the result"
                    }
                },
                "required": ["success", "message"]
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
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "Whether the wait action succeeded"
                    },
                    "message": {
                        "type": "string",
                        "description": "Status message describing the result"
                    }
                },
                "required": ["success", "message"]
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
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "Whether the go back action succeeded"
                    },
                    "message": {
                        "type": "string",
                        "description": "Status message describing the result"
                    }
                },
                "required": ["success", "message"]
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
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "Whether navigating to Google succeeded"
                    },
                    "message": {
                        "type": "string",
                        "description": "Status message describing the result"
                    }
                },
                "required": ["success", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_website",
            "description": "Check the current state of the webpage without performing any action. Returns a fresh screenshot with labeled elements, the list of clickable elements, and all visible text on the page. Use this to understand what's currently on the page.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "Whether checking the page succeeded"
                    },
                    "message": {
                        "type": "string",
                        "description": "Status message"
                    },
                    "screenshot": {
                        "type": "string",
                        "description": "Screenshot image with labeled elements showing current page state"
                    },
                    "web_elements": {
                        "type": "string",
                        "description": "Text list of ONLY clickable/interactive elements with labels (format: '[label]: element_text'). Use these labels to click/type."
                    },
                    "website_texts": {
                        "type": "string",
                        "description": "Full visible text content from the entire webpage including paragraphs, headings, prices, articles, etc. Use this to extract information."
                    }
                },
                "required": ["success", "message", "screenshot", "web_elements", "website_texts"]
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
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "Whether the task was completed successfully"
                    },
                    "message": {
                        "type": "string",
                        "description": "Task completion message"
                    }
                },
                "required": ["success", "message"]
            }
        }
    }
]


SYSTEM_PROMPT = """Complete the user's goal by analyzing webpage screenshots and take actions iteratively.

Screenshots show numerical labels in the TOP LEFT corner of interactive elements. 
Use tools provided that can help to understand image contents to identify which element labels to interact with.
Every time when you call a tool, a screenshot would be fed back as a fresh image input for you to anlayze and take the next action.

Notes:
- Numerical labels identify clickable elements, textboxes, etc.
- If an action doesn't work, try a different approach (e.g., scroll to reveal more content)
- Complete one action per iteration
"""


class SequrityCUA:
    """Computer-Use Agent using Sequrity's tool-based architecture."""

    def __init__(self, api_key: str, base_url: str, model: str = "gpt-4o", session_id: str = None):
        self.client = SequrityAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.session_id = session_id
        self.messages = []
        self.logger = logging.getLogger(__name__)

        # Progress tracking
        self.failed_actions = []
        self.last_url = None
        self.stuck_count = 0

    def add_system_prompt(self):
        """Add system prompt with tool usage instructions."""
        self.messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT
        })

    def add_observation(self, screenshot_b64: str, web_elements_text: str):
        """Add a new observation (screenshot + element text) to the conversation."""

        observation_text = (
            f"Observation: Current page state. Continue working toward completing the original task.\n\n"
            f"Web elements (label: text content):\n{web_elements_text}\n\n"
            f"CRITICAL REQUIREMENTS:\n"
            f"- Element labels shown above are ONLY valid for THIS observation. After any action (click, type, etc.), "
            f"the page may change and element labels will be completely different in the next observation.\n"
            f"- Do NOT reference element labels from previous observations. ONLY use labels from the CURRENT observation.\n"
            f"- You MUST call answer() to complete the task. Do NOT claim task is finished without calling answer().\n"
            f"- If you cannot complete the task or are stuck, return with an explanation describing why you cannot proceed.\n\n"
            f"TASK GUIDELINES:\n"
            f"- This is a multi-step task. Keep working until you find the final answer.\n"
            f"- Do NOT set final_return_value for intermediate actions (clicking, typing, etc).\n"
            f"- ONLY set final_return_value when you call answer() with the actual result requested in the task.\n"
            f"- You can use parse_image_with_ai to help analyze the screenshot if needed.\n"
            f"- PREFER using direct actions (click_element, type_text, scroll_page, etc.) for web navigation.\n"
            f"- ONLY use plan_and_execute when the task requires complex reasoning or data extraction that cannot be accomplished with direct actions.\n"
            f"- For sequential navigation (click → wait → click), use direct tool calls instead of plan_and_execute."
        )

        # Send image with observation - server will convert to UUID automatically
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
                - session_id_before_clear: str (session ID before it was cleared)
            or None if no tool call was made
        """
        self.logger.info("Calling Sequrity API with tools...")

        # Build request parameters
        request_params = {
            "model": self.model,
            "messages": self.messages,
            "tools": TOOLS,
            "max_tokens": 2000,
            "timeout": 300,  # Increase timeout for vision requests
        }

        # Add session_id if provided
        if self.session_id:
            request_params["session_id"] = self.session_id

        # Capture session ID BEFORE making the call (in case it gets cleared after)
        session_id_before_clear = self.client._session_id

        response = self.client.chat.completions.create(**request_params)

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
                "tool_call_id": tool_call.id,
                "session_id_before_clear": session_id_before_clear
            }

        # No tool call - just reasoning
        self.messages.append(assistant_msg)
        self.logger.warning("No tool call in response, only reasoning")

        # Return session ID even when no action, so we can retrieve PLLM program
        return {"session_id_before_clear": session_id_before_clear} if session_id_before_clear else None

    def report_tool_result(self, tool_call_id: str, success: bool, message: str = "", screenshot_b64: str = None, web_text: str = None, website_texts: str = None):
        """Report the result of a tool execution back to the assistant.

        Tool results must be JSON strings. Screenshots are included as fields in the JSON
        and will be converted to UUIDs by the server.
        """
        # Build result as a dictionary
        result = {
            "success": success,
            "message": message
        }

        # Add screenshot as a field if provided (server will convert to UUID)
        if screenshot_b64:
            result["screenshot"] = f"data:image/png;base64,{screenshot_b64}"

        # Add web elements (clickable elements with labels) if provided
        if web_text:
            result["web_elements"] = web_text

        # Add website_texts (full page text content) if provided
        if website_texts:
            result["website_texts"] = website_texts

        # Tool messages must have a simple string content (JSON formatted)
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(result)
        })

    def track_progress(self, action: dict, success: bool, current_url: str):
        """
        Track progress and detect if we're stuck.

        Args:
            action: The action that was attempted
            success: Whether the action succeeded
            current_url: Current page URL
        """
        # Track failed actions
        if not success:
            action_key = f"{action['tool_name']}:{json.dumps(action['arguments'])}"
            self.failed_actions.append(action_key)

            # Check if we've failed the same action multiple times recently
            if len(self.failed_actions) >= 3:
                recent_failures = self.failed_actions[-3:]
                if len(set(recent_failures)) == 1:  # Same action failed 3 times
                    self.stuck_count += 1
                    self.logger.warning(f"Detected repeated failure: {action_key}")
                    return True

        # Check if URL hasn't changed for several iterations (no progress)
        if self.last_url == current_url:
            # Exclude certain actions that don't change URL
            non_navigation_actions = ["wait", "scroll_page", "type_text"]
            if action['tool_name'] not in non_navigation_actions:
                self.stuck_count += 1
        else:
            self.stuck_count = 0  # Reset if we made progress

        self.last_url = current_url

        # Consider stuck if no progress for 3+ iterations
        return self.stuck_count >= 3

    def send_pllm_retry_command(self):
        """
        Send a PLLM retry command when stuck.
        This adds a special message to trigger policy-level retry logic.
        """
        self.logger.warning("Sending PLLM retry command due to stuck state")
        self.messages.append({
            "role": "user",
            "content": "PLLM_RETRY: The task appears to be stuck with no progress. Please retry with a different approach or strategy."
        })

    def reset_session(self):
        """Reset session for a new task."""
        self.client.reset_session()
        self.messages = []
        self.failed_actions = []
        self.last_url = None
        self.stuck_count = 0


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
                    try:
                        # Scroll element into view
                        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
                        time.sleep(0.5)

                        # Prevent opening in new tab/window
                        driver.execute_script("arguments[0].setAttribute('target', '_self')", element)

                        # Click the element
                        element.click()
                        time.sleep(3)
                        return True, f"Clicked element [{label}]"
                    except Exception as click_error:
                        # If normal click fails, try JavaScript click
                        logger.warning(f"Normal click failed: {click_error}, trying JS click")
                        driver.execute_script("arguments[0].click();", element)
                        time.sleep(3)
                        return True, f"Clicked element [{label}] (via JS)"
            return False, f"Element with label [{label}] not found"

        elif tool_name == "type_text":
            label = args["label"]
            content = args["content"]
            for elem_info in labeled_elements:
                if str(elem_info["label"]) == str(label):
                    element = elem_info["element"]

                    # Scroll into view
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
                    time.sleep(0.5)

                    # Clear field thoroughly
                    try:
                        element.clear()
                        # Select all and delete (platform-specific)
                        if platform.system() == 'Darwin':
                            element.send_keys(Keys.COMMAND + "a")
                        else:
                            element.send_keys(Keys.CONTROL + "a")
                        element.send_keys(" ")
                        element.send_keys(Keys.BACKSPACE)
                    except:
                        pass

                    # Use ActionChains for more reliable typing
                    actions = ActionChains(driver)
                    actions.click(element).perform()
                    actions.pause(1)

                    # Prevent space from scrolling page
                    try:
                        driver.execute_script("""window.onkeydown = function(e) {if(e.keyCode == 32 && e.target.type != 'text' && e.target.type != 'textarea' && e.target.type != 'search') {e.preventDefault();}};""")
                    except:
                        pass

                    # Type content
                    actions.send_keys(content)
                    actions.pause(2)
                    actions.send_keys(Keys.RETURN)
                    actions.perform()

                    time.sleep(5)  # Wait for page to load/respond
                    return True, f"Typed '{content}' into element [{label}]"
            return False, f"Element with label [{label}] not found"

        elif tool_name == "scroll_page":
            target = args["target"]
            direction = args["direction"]

            if target.upper() == "WINDOW":
                # Get window height and scroll 2/3 of it (same as run.py)
                window_height = driver.execute_script("return window.innerHeight;")
                scroll_amount = window_height * 2 // 3
                if direction == "down":
                    driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
                else:
                    driver.execute_script(f"window.scrollBy(0, {-scroll_amount});")
            else:
                # Scroll specific element using focus + keyboard (same as run.py)
                for elem_info in labeled_elements:
                    if str(elem_info["label"]) == str(target):
                        element = elem_info["element"]
                        actions = ActionChains(driver)
                        driver.execute_script("arguments[0].focus();", element)
                        if direction == "down":
                            actions.key_down(Keys.ALT).send_keys(Keys.ARROW_DOWN).key_up(Keys.ALT).perform()
                        else:
                            actions.key_down(Keys.ALT).send_keys(Keys.ARROW_UP).key_up(Keys.ALT).perform()
                        break
            time.sleep(3)
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

        elif tool_name == "check_website":
            # No action needed - just return success so main loop captures current state
            return True, "Checked current page state"

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
    parser.add_argument("--session_id", type=str, default=None, help="Session ID for continuing a previous session")
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

    # Build task message with examples
    task_message = f"""Task: {args.task}

Please navigate to {args.url} and complete the task.

IMPORTANT: Understanding check_website() output:

check_website() returns a dictionary with:
- "screenshot": Image with numbered labels on clickable elements (buttons, links, inputs)
- "web_elements": Text list showing ONLY the clickable elements with their labels (format: "[label]: element_text")
- "website_texts": Full visible text content from the entire webpage (paragraphs, articles, prices, headings, etc.)
- "success": boolean
- "message": status message

**CRITICAL**:
- web_elements = ONLY clickable elements (for finding which label to click)
- website_texts = FULL page text content (for extracting information like prices, birth years, articles)

Example of what check_website() returns:
```python
obs = check_website()
# obs is a dictionary:
# {{"success": true,
#   "message": "...",
#   "web_elements": "[2]: <input> Search\\n[3]: <button> Submit\\n[5]: Home\\n[6]: Products",
#   "website_texts": "Welcome to our store...iPhone 15 Pro $999...Free shipping...",
#   "screenshot": "uuid://xxxxx"}}

# Access fields using dictionary keys:
elements_text = obs["web_elements"]  # For finding labels to click
page_content = obs["website_texts"]  # For extracting information
screenshot_uuid = obs["screenshot"]  # For visual analysis
```

---

## Example 1: Finding and clicking an element

```python
final_return_value = None

# Check current page
obs1 = check_website()

# Only parse web_elements to find which NUMERIC label to click
# web_elements format: "[2]: <button> Products\n[5]: <a> About\n[7]: Home"
# You need to extract the NUMBER from brackets [2], [5], [7]
elements_text = obs1["web_elements"]

# Use parse_with_ai to extract the NUMERIC label (e.g., "2", "5", "7")
output_schema = {{"type": "object", "properties": {{"have_enough_info": {{"type": "boolean"}}, "result": {{"type": "string", "description": "The numeric label like '2' or '5', NOT the text"}}}}, "required": ["have_enough_info", "result"]}}
query = "From this list, find the NUMERIC label (the number in brackets) of the 'Products' button or link. Return ONLY the number as a string, like '2' or '5', NOT the button text. List: " + elements_text
result = parse_with_ai(query=query, output_schema=output_schema)

if result["have_enough_info"]:
    products_label = result["result"]  # This should be like "2" or "5"
    click_element(label=products_label)
    wait()

    # CRITICAL: Get fresh observation after action
    obs2 = check_website()
    # obs2["web_elements"] now has DIFFERENT labels!
```

---

## Example 2: Extracting information from page content

```python
final_return_value = None

# Navigate to product page first...
obs = check_website()
elements = obs["web_elements"]

# Find and click on iPhone product link - extract NUMERIC label ONLY
output_schema = {{"type": "object", "properties": {{"have_enough_info": {{"type": "boolean"}}, "result": {{"type": "string", "description": "Numeric label only, like '3' or '12'"}}}}, "required": ["have_enough_info", "result"]}}
query = "Find the NUMERIC label (number in brackets like '[8]' or '[15]') of the 'iPhone 15 Pro' link. Return ONLY the number as a string. List: " + elements
result = parse_with_ai(query=query, output_schema=output_schema)

if result["have_enough_info"]:
    iphone_label = result["result"]  # This must be like "8", NOT "iPhone 15 Pro"
    click_element(label=iphone_label)
    wait()

    obs2 = check_website()
    page_text = obs2["website_texts"]  # This contains FULL page text!

    # Extract price from website_texts (NOT from web_elements which only has clickable items)
    output_schema_2 = {{"type": "object", "properties": {{"have_enough_info": {{"type": "boolean"}}, "result": {{"type": "string"}}}}, "required": ["have_enough_info", "result"]}}
    query_2 = "Extract the price of the iPhone 15 Pro 256GB model from this text: " + page_text
    price_info = parse_with_ai(query=query_2, output_schema=output_schema_2)

    if price_info["have_enough_info"]:
        final_return_value = price_info["result"]
        answer(content=price_info["result"])
```

---

## Example 3: Typing in search box

```python
final_return_value = None

obs = check_website()
elements = obs["web_elements"]

# Find search input label
output_schema = {{"type": "object", "properties": {{"have_enough_info": {{"type": "boolean"}}, "result": {{"type": "string"}}}}, "required": ["have_enough_info", "result"]}}
query = "Find the label of the search input box from: " + elements
result = parse_with_ai(query=query, output_schema=output_schema)

if result["have_enough_info"]:
    search_label = result["result"]
    type_text(label=search_label, content="iPhone 15")
    wait()

    # MUST check_website() again after typing - labels changed!
    obs2 = check_website()
```

---

## WRONG Examples (DO NOT DO THIS):

```python
# WRONG: Using element labels from old observation
obs1 = check_website()
click_element(label="5")  # Page changes
click_element(label="8")  # ERROR! Label 8 from obs1 may not exist anymore

# WRONG: Trying to read full page text/prices from web_elements
obs = check_website()
elements = obs["web_elements"]  # Only has "[5]: Home\\n[6]: About\\n[7]: Contact"
# Trying to find "$999" or article paragraphs in elements - WON'T WORK!
# Use obs["website_texts"] instead!

# WRONG: Treating result as object with dot notation
obs = check_website()
text = obs.web_elements  # ERROR! Use obs["web_elements"] instead

# WRONG: Converting entire response to string
obs = check_website()
obs_text = str(obs)  # This includes success, message, screenshot UUID - messy!
# Instead: obs["web_elements"] for labels, obs["website_texts"] for content

# WRONG: Using label text instead of label number
obs = check_website()
elements = obs["web_elements"]  # Contains "[2]: Search button"
click_element(label="Search button")  # ERROR! Use label="2" instead
```

---

Remember:
1. web_elements = clickable elements ONLY with numeric labels (for clicking/typing)
2. website_texts = FULL page text content (for extracting information)
3. screenshot = full visual content (for visual analysis if needed)
4. Always check_website() after each action to get fresh labels
5. Access fields with dictionary keys: obs["web_elements"], obs["website_texts"], obs["screenshot"]
6. Extract NUMERIC labels from web_elements, NOT the text
"""

    agent.messages.append({
        "role": "user",
        "content": task_message
    })

    # Navigate to starting URL
    driver.get(args.url)
    time.sleep(3)

    task_success = False

    # Main loop
    # Only add initial observation before first action
    first_iteration = True
    actions_without_progress = 0
    max_actions_without_progress = 5

    # Store web_elements from previous iteration's screenshot for execution
    cached_web_elements = None
    cached_web_text = None

    for iteration in range(args.max_iterations):
        logger.info(f"\n{'='*50}\nIteration {iteration + 1}\n{'='*50}")

        # For first iteration, capture initial page state
        if first_iteration:
            # Draw labels on page
            rects, web_elements, web_text = get_web_element_rect(driver, fix_color=True)

            # Capture screenshot
            screenshot_path = os.path.join(task_dir, f'screenshot{iteration + 1}.png')
            driver.save_screenshot(screenshot_path)

            with open(screenshot_path, 'rb') as f:
                screenshot_b64 = base64.b64encode(f.read()).decode('utf-8')

            # Add initial observation
            agent.add_observation(screenshot_b64, web_text)

            # Cache these elements for execution
            cached_web_elements = web_elements
            cached_web_text = web_text
            first_iteration = False

        # Get next action
        action = agent.get_next_action()

        if not action or 'tool_name' not in action:
            # Model stopped without calling answer()
            logger.error("Agent stopped generating actions without calling answer()")
            break

        logger.info(f"Action: {action['tool_name']}({action['arguments']})")
        if action.get('reasoning'):
            logger.info(f"Reasoning: {action['reasoning']}")

        # Check if this is the answer
        if action['tool_name'] == "answer":
            logger.info(f"\n{'='*50}\nFINAL ANSWER\n{'='*50}")
            logger.info(action['arguments']['content'])
            agent.report_tool_result(action['tool_call_id'], True, "Task completed")
            task_success = True
            break

        # Build labeled elements list using CACHED elements from previous screenshot
        # This ensures the labels match what the PLLM saw in the screenshot
        if cached_web_elements is None:
            logger.error("No cached web elements available for execution!")
            break

        labeled_elements = []
        for idx, elem in enumerate(cached_web_elements):
            labeled_elements.append({
                "label": str(idx),
                "element": elem
            })

        logger.info(f"Using {len(labeled_elements)} cached elements from previous screenshot")

        # Execute action
        success, message = execute_action(driver, action, labeled_elements)
        logger.info(f"Result: {'✓' if success else '✗'} {message}")

        # Only capture and send page state for check_website tool
        if action['tool_name'] == 'check_website':
            # Capture page state AFTER action
            time.sleep(1)  # Brief wait for page to update
            rects, web_elements, web_text = get_web_element_rect(driver, fix_color=True)

            # Cache these elements for the NEXT action
            cached_web_elements = web_elements
            cached_web_text = web_text

            # Capture full page text content
            try:
                from selenium.webdriver.common.by import By
                website_texts = driver.find_element(By.TAG_NAME, "body").text
            except Exception as e:
                logger.warning(f"Failed to capture website_texts: {e}")
                website_texts = ""

            screenshot_path = os.path.join(task_dir, f'screenshot{iteration + 1}_result.png')
            driver.save_screenshot(screenshot_path)

            with open(screenshot_path, 'rb') as f:
                screenshot_b64 = base64.b64encode(f.read()).decode('utf-8')

            # Report result WITH screenshot, web_elements, and website_texts
            agent.report_tool_result(action['tool_call_id'], success, message, screenshot_b64, web_text, website_texts)
        else:
            # For all other tools, just report success/message without page state
            agent.report_tool_result(action['tool_call_id'], success, message)

            # Still need to update cached elements for next action
            time.sleep(1)
            rects, web_elements, web_text = get_web_element_rect(driver, fix_color=True)
            cached_web_elements = web_elements
            cached_web_text = web_text

        if not success:
            logger.warning("Action failed, agent will retry with different approach")
            actions_without_progress += 1
        else:
            # Reset progress counter on successful action
            current_url = driver.current_url
            if current_url != agent.last_url:
                actions_without_progress = 0
                agent.last_url = current_url

        # Check if stuck (too many actions without progress)
        if actions_without_progress >= max_actions_without_progress:
            failure_reason = f"Stuck: {actions_without_progress} consecutive actions without progress"
            logger.error(f"{failure_reason}")
            break

    # End of main iteration loop
    if task_success:
        logger.info(f"\n{'='*60}\n✅ TASK COMPLETED SUCCESSFULLY\n{'='*60}")
    else:
        logger.error(f"\n{'='*60}\n❌ TASK FAILED\n{'='*60}")

    driver.quit()
    logger.info("Session complete")


if __name__ == "__main__":
    main()
