import os

# Set PLAYWRIGHT_BROWSERS_PATH before Playwright module is imported
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "D:\\playwright-browsers"

import base64
import io
import re
import asyncio
import inspect
import logging
from html.parser import HTMLParser
from typing import Optional

from PIL import Image
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeoutError

from core.actions import AgentAction, ActionType
from config.settings import settings

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Custom exception for browser execution errors."""
    pass


def condense_dom(raw_html: str) -> str:
    """
    Parses raw HTML and condenses it into a structural representation prioritizing interactive
    elements, headings, and significant text content. Designed for unit testability and as a fallback.
    """
    class CondenserParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.result = []
            self.skip_tags = {'script', 'style', 'svg', 'noscript'}
            self.interactive_tags = {'a', 'button', 'input', 'textarea', 'select', 'form'}
            self.heading_tags = {f'h{i}' for i in range(1, 7)}
            self.ignore_depth = 0
            self.current_interactive = None
            self.current_heading = None
            
        def handle_starttag(self, tag, attrs):
            if tag in self.skip_tags:
                self.ignore_depth += 1
                return
            
            if self.ignore_depth > 0:
                return

            attr_dict = dict(attrs)
            
            # Skip hidden elements (simple check for python parser)
            style = attr_dict.get('style', '').lower()
            if 'display: none' in style or 'display:none' in style or 'visibility: hidden' in style or 'visibility:hidden' in style:
                self.ignore_depth += 1
                return
            if attr_dict.get('aria-hidden') == 'true' or attr_dict.get('type') == 'hidden':
                self.ignore_depth += 1
                return
            
            if tag in self.interactive_tags or tag in self.heading_tags:
                tag_id = attr_dict.get('id')
                data_testid = attr_dict.get('data-testid')
                aria_label = attr_dict.get('aria-label')
                name = attr_dict.get('name')
                
                # Priority: id > data-testid > aria-label > name attribute > tag
                selector = ""
                if tag_id:
                    selector = f"{tag}#{tag_id}"
                elif data_testid:
                    selector = f"{tag}[data-testid='{data_testid}']"
                elif aria_label:
                    selector = f"{tag}[aria-label='{aria_label}']"
                elif name:
                    selector = f"{tag}[name='{name}']"
                else:
                    classes = attr_dict.get('class', '').split()
                    if classes:
                        selector = f"{tag}.{classes[0]}"
                    else:
                        selector = tag
                
                element_data = {'tag': tag, 'selector': selector, 'attrs': attr_dict, 'text': ""}
                if tag in self.interactive_tags:
                    self.current_interactive = element_data
                else:
                    self.current_heading = element_data

        def handle_endtag(self, tag):
            if tag in self.skip_tags:
                if self.ignore_depth > 0:
                    self.ignore_depth -= 1
                return
            
            if self.ignore_depth > 0:
                return
                
            if self.current_interactive and self.current_interactive['tag'] == tag:
                # Build representation
                el = self.current_interactive
                rep = f"[{el['selector']}]"
                text = el['text'].strip()
                
                if tag == 'input':
                    in_type = el['attrs'].get('type', 'text')
                    rep += f" type={in_type}"
                    if 'placeholder' in el['attrs']:
                        rep += f" placeholder=\"{el['attrs']['placeholder']}\""
                    if 'name' in el['attrs']:
                        rep += f" name=\"{el['attrs']['name']}\""
                elif tag == 'a':
                    if text:
                        rep += f" \"{text[:60]}\""
                    href = el['attrs'].get('href')
                    if href:
                        rep += f" -> href={href}"
                else:
                    if text:
                        rep += f" \"{text[:60]}\""
                        
                self.result.append(rep)
                self.current_interactive = None
                
            elif self.current_heading and self.current_heading['tag'] == tag:
                el = self.current_heading
                rep = f"[{el['selector']}]"
                text = el['text'].strip()
                if text:
                    rep += f" \"{text[:60]}\""
                self.result.append(rep)
                self.current_heading = None

        def handle_data(self, data):
            if self.ignore_depth > 0:
                return
            
            text = data.strip()
            if not text:
                return
                
            if self.current_interactive:
                self.current_interactive['text'] += text + " "
            elif self.current_heading:
                self.current_heading['text'] += text + " "
            elif len(text) > 20:
                # Add standalone text nodes
                self.result.append(f"[text] \"{text[:60]}\"")

    parser = CondenserParser()
    parser.feed(raw_html)
    
    output = "\n".join(parser.result)
    
    # Cap at ~12000 chars roughly.
    if len(output) > 12000:
        return output[:11997] + "..."
    return output


class BrowserController:
    """Handles browser automation using Playwright and condensed DOM extraction."""

    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.cdp_session = None
        self.screencast_callback = None
        # Use settings if available, otherwise default to 1280
        self.screenshot_max_width = getattr(settings, 'SCREENSHOT_MAX_WIDTH', 1280)

    async def launch(self, headless: bool = True):
        """Launches the Chromium browser via Playwright."""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=headless)
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 1024},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="en-US"
            )
            self.page = await self.context.new_page()
            await self.page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            logger.info(f"Browser launched (headless={headless})")
        except Exception as e:
            logger.error(f"Failed to launch browser: {e}")
            raise ExecutionError(f"Failed to launch browser: {e}")

    async def start_screencast(self, callback):
        """Starts real-time high-FPS CDP screencast video stream."""
        if not self.context or not self.page:
            return
        try:
            self.screencast_callback = callback
            self.cdp_session = await self.context.new_cdp_session(self.page)
            
            async def on_frame(params):
                session_id = params.get("sessionId")
                data_base64 = params.get("data")
                if self.cdp_session:
                    try:
                        await self.cdp_session.send("Page.screencastFrameAck", {"sessionId": session_id})
                    except Exception:
                        pass
                if self.screencast_callback and data_base64:
                    try:
                        res = self.screencast_callback(data_base64)
                        if inspect.isawaitable(res):
                            await res
                    except Exception as frame_err:
                        logger.debug(f"Frame callback error: {frame_err}")

            self.cdp_session.on("Page.screencastFrame", lambda params: asyncio.create_task(on_frame(params)))
            await self.cdp_session.send("Page.startScreencast", {
                "format": "jpeg",
                "quality": 60,
                "maxWidth": 1280,
                "maxHeight": 1024,
                "everyNthFrame": 1
            })
            logger.info("CDP High-FPS Live Screencast stream started")
        except Exception as e:
            logger.warning(f"Could not start CDP Screencast: {e}")

    async def stop_screencast(self):
        """Stops CDP screencast stream."""
        if self.cdp_session:
            try:
                await self.cdp_session.send("Page.stopScreencast")
            except Exception:
                pass
            self.cdp_session = None
            self.screencast_callback = None

    async def close(self):
        """Closes the browser gracefully."""
        await self.stop_screencast()
        if self.page:
            await self.page.close()
            self.page = None
        if self.context:
            await self.context.close()
            self.context = None
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        logger.info("Browser closed")

    def get_current_url(self) -> str:
        """Returns the current page URL."""
        if not self.page:
            return ""
        return self.page.url

    async def capture_screenshot(self) -> str:
        """
        Takes a full-page screenshot, downscales if wider than SCREENSHOT_MAX_WIDTH.
        Returns as base64 string.
        """
        if not self.page:
            raise ExecutionError("Browser page is not initialized.")
            
        try:
            screenshot_bytes = await self.page.screenshot(full_page=True)
            
            # Resize using PIL if needed
            image = Image.open(io.BytesIO(screenshot_bytes))
            if image.width > self.screenshot_max_width:
                ratio = self.screenshot_max_width / image.width
                new_height = int(image.height * ratio)
                image = image.resize((self.screenshot_max_width, new_height), Image.LANCZOS)
                
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            img_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            return img_b64
        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
            raise ExecutionError(f"Screenshot failed: {e}")

    async def extract_condensed_dom(self) -> str:
        """
        Runs JS in the page to extract a condensed DOM prioritizing interactive elements.
        Outputs a flat indented list, capped at ~12000 chars.
        """
        if not self.page:
            raise ExecutionError("Browser page is not initialized.")

        js_script = '''
        () => {
            function getSelector(el) {
                if (el.id) return el.tagName.toLowerCase() + '#' + el.id;
                if (el.getAttribute('data-testid')) return el.tagName.toLowerCase() + '[data-testid="' + el.getAttribute('data-testid') + '"]';
                if (el.getAttribute('aria-label')) return el.tagName.toLowerCase() + '[aria-label="' + el.getAttribute('aria-label') + '"]';
                if (el.getAttribute('name')) return el.tagName.toLowerCase() + '[name="' + el.getAttribute('name') + '"]';
                
                // nth-of-type fallback
                let tag = el.tagName.toLowerCase();
                let parent = el.parentNode;
                if (!parent) return tag;
                let siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
                if (siblings.length === 1) return tag;
                let index = siblings.indexOf(el) + 1;
                return tag + ':nth-of-type(' + index + ')';
            }

            function isVisible(el) {
                if (el.nodeType !== 1) return true; // text nodes
                let style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                if (el.getAttribute('aria-hidden') === 'true') return false;
                if (el.tagName === 'INPUT' && el.type === 'hidden') return false;
                return true;
            }

            let elements = [];
            let walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
                acceptNode: function(node) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        let tag = node.tagName.toLowerCase();
                        if (['script', 'style', 'svg', 'noscript'].includes(tag)) return NodeFilter.FILTER_REJECT;
                        if (!isVisible(node)) return NodeFilter.FILTER_REJECT;
                        if (['a', 'button', 'input', 'textarea', 'select', 'form'].includes(tag) || /^h[1-6]$/.test(tag)) {
                            return NodeFilter.FILTER_ACCEPT;
                        }
                        return NodeFilter.FILTER_SKIP;
                    } else if (node.nodeType === Node.TEXT_NODE) {
                        if (!node.nodeValue.trim() || node.nodeValue.trim().length <= 20) return NodeFilter.FILTER_SKIP;
                        if (!isVisible(node.parentElement)) return NodeFilter.FILTER_REJECT;
                        return NodeFilter.FILTER_ACCEPT;
                    }
                }
            });

            let currentNode;
            while (currentNode = walker.nextNode()) {
                if (currentNode.nodeType === Node.ELEMENT_NODE) {
                    let tag = currentNode.tagName.toLowerCase();
                    let selector = getSelector(currentNode);
                    let rep = `[${selector}]`;
                    let text = currentNode.textContent.trim().substring(0, 60).replace(/\\s+/g, ' ');

                    if (tag === 'input') {
                        let inType = currentNode.getAttribute('type') || 'text';
                        rep += ` type=${inType}`;
                        let ph = currentNode.getAttribute('placeholder');
                        if (ph) rep += ` placeholder="${ph}"`;
                        let name = currentNode.getAttribute('name');
                        if (name) rep += ` name="${name}"`;
                    } else if (tag === 'a') {
                        if (text) rep += ` "${text}"`;
                        let href = currentNode.getAttribute('href');
                        if (href) rep += ` -> href=${href}`;
                    } else {
                        if (text) rep += ` "${text}"`;
                    }
                    elements.push({type: 'interactive', rep: rep});
                } else if (currentNode.nodeType === Node.TEXT_NODE) {
                    let text = currentNode.nodeValue.trim().substring(0, 60).replace(/\\s+/g, ' ');
                    elements.push({type: 'text', rep: `[text] "${text}"`});
                }
            }

            let result = elements.map(e => e.rep).join('\\n');
            if (result.length > 12000) {
                return result.substring(0, 11997) + '...';
            }
            return result;
        }
        '''
        try:
            condensed = await self.page.evaluate(js_script)
            return condensed
        except Exception as e:
            logger.error(f"Failed to extract condensed DOM via JS: {e}")
            raise ExecutionError(f"DOM extraction failed: {e}")

    async def execute_action(self, action: AgentAction) -> str:
        """
        Executes a specific action via Playwright and returns a descriptive string of the outcome.
        """
        if not self.page:
            raise ExecutionError("Browser page is not initialized.")
            
        try:
            if action.action == ActionType.navigate:
                url = action.value or action.target
                if not url:
                    raise ExecutionError("URL not provided for navigation.")
                if not (url.startswith("http://") or url.startswith("https://")):
                    url = "https://" + url
                await self.page.goto(url, timeout=30000)
                return f"Navigated to {url}"
                
            elif action.action == ActionType.click:
                selector = action.target
                if not selector:
                    raise ExecutionError("Selector not provided for click.")
                try:
                    await self.page.evaluate(f"(sel) => {{ const el = document.querySelector(sel); if(el) el.scrollIntoView({{behavior: 'instant', block: 'center'}}); }}", selector)
                    await self.page.click(selector, timeout=5000)
                except Exception:
                    clicked = await self.page.evaluate(f"(sel) => {{ const el = document.querySelector(sel); if(el) {{ el.click(); return true; }} return false; }}", selector)
                    if not clicked:
                        raise ExecutionError(f"Could not find or click element: {selector}")
                return f"Clicked on {selector}"
                
            elif action.action == ActionType.type:
                selector = action.target
                text = action.value
                if not selector or not text:
                    raise ExecutionError("Selector or text missing for type action.")
                try:
                    await self.page.evaluate(f"(sel) => {{ const el = document.querySelector(sel); if(el) el.scrollIntoView({{behavior: 'instant', block: 'center'}}); }}", selector)
                    await self.page.fill(selector, text, timeout=5000)
                except Exception:
                    filled = await self.page.evaluate(f"([sel, val]) => {{ const el = document.querySelector(sel); if(el) {{ el.value = val; el.dispatchEvent(new Event('input', {{bubbles:true}})); el.dispatchEvent(new Event('change', {{bubbles:true}})); return true; }} return false; }}", [selector, text])
                    if not filled:
                        raise ExecutionError(f"Could not find or type into element: {selector}")
                return f"Typed into {selector}"
                
            elif action.action == ActionType.scroll:
                direction = action.value or "down"
                if direction == 'down':
                    await self.page.evaluate("window.scrollBy(0, window.innerHeight)")
                    return "Scrolled down one page"
                elif direction == 'up':
                    await self.page.evaluate("window.scrollBy(0, -window.innerHeight)")
                    return "Scrolled up one page"
                elif direction == 'top':
                    await self.page.evaluate("window.scrollTo(0, 0)")
                    return "Scrolled to top"
                elif direction == 'bottom':
                    await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    return "Scrolled to bottom"
                else:
                    try:
                        pixels = int(direction)
                        await self.page.evaluate(f"window.scrollBy(0, {pixels})")
                        return f"Scrolled by {pixels} pixels"
                    except ValueError:
                        raise ExecutionError(f"Invalid scroll direction: {direction}")
                        
            elif action.action == ActionType.extract:
                selector = action.target
                if not selector:
                    raise ExecutionError("Selector missing for extraction.")
                text = await self.page.evaluate(f"document.querySelector('{selector}') ? document.querySelector('{selector}').textContent.trim() : null")
                return f"Extracted text: {text}"
                
            elif action.action == ActionType.screenshot:
                await self.capture_screenshot()
                return "Captured extra screenshot"
                
            elif action.action == ActionType.wait:
                ms = 1000
                try:
                    if action.value:
                        ms = int(action.value)
                except (ValueError, TypeError):
                    pass
                ms = min(ms, 5000)  # cap at 5000ms
                await self.page.wait_for_timeout(ms)
                return f"Waited for {ms}ms"
                
            elif action.action in (ActionType.complete, ActionType.abort):
                return action.value or f"Action {action.action.value}d"
                
            else:
                raise ExecutionError(f"Unsupported action type: {action.action}")
                
        except PlaywrightTimeoutError as e:
            raise ExecutionError(f"Action timed out: {e}")
        except Exception as e:
            raise ExecutionError(f"Action execution failed: {e}")
