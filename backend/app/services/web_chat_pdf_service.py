"""Automated Web Chat to PDF Generator Service using Playwright Chromium."""

import asyncio
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from app.core.config import settings

logger = logging.getLogger(__name__)

PRINT_ENHANCEMENT_CSS = """
/* 1. Hide web chrome, sidebars, buttons, textareas, and navigation */
header, nav, aside, form, textarea, button, input,
[class*="sidebar"], [class*="composer"], [class*="bottom-"],
[class*="feedback"], [aria-label*="Feedback"], [aria-label*="Copy"],
[aria-label*="Share"], [role="navigation"], [class*="gizmo"],
[class*="scroll-to-bottom"], [data-testid*="send-button"],
[class*="thread-footer"], [class*="input-area"] {
    display: none !important;
}

/* 2. Page layout & typography for clean academic reading */
html, body {
    background: #ffffff !important;
    color: #172033 !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
    font-size: 15px !important;
    line-height: 1.65 !important;
    margin: 0 !important;
    padding: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    height: auto !important;
    min-height: 0 !important;
    overflow: visible !important;
}

main, article, [class*="conversation"], [class*="chat-"] {
    max-width: 100% !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
}

body:has(#univflow-print-document) > *:not(#univflow-print-document) {
    display: none !important;
}

#univflow-print-document {
    display: block !important;
    width: 100% !important;
    max-width: none !important;
    margin: 0 !important;
    padding: 0 !important;
    color: #172033 !important;
    font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif !important;
}

.pdf-document-title {
    margin: 0 0 28px;
    padding: 0;
}

.pdf-document-title p {
    color: #5b65a8 !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: .1em !important;
    margin: 0 0 4px !important;
    text-transform: uppercase;
}

.pdf-document-title h1 {
    color: #172033 !important;
    font-size: 24px !important;
    line-height: 1.25 !important;
    margin: 0 !important;
}

.pdf-turn {
    box-sizing: border-box !important;
    width: 100% !important;
    max-width: none !important;
    margin: 0 0 24px !important;
    padding: 0 !important;
    border: 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    break-inside: auto !important;
    page-break-inside: auto !important;
    orphans: 3;
    widows: 3;
}

.pdf-turn-user {
    background: transparent !important;
}

.pdf-turn-assistant {
    background: transparent !important;
}

.pdf-turn-label {
    color: #5f6368 !important;
    display: block !important;
    font-size: 9px !important;
    font-weight: 700 !important;
    letter-spacing: .1em !important;
    line-height: 1.4 !important;
    margin: 0 0 8px !important;
    text-transform: uppercase;
    break-after: avoid-page !important;
    page-break-after: avoid !important;
}

.pdf-turn-content {
    color: #172033 !important;
    font-size: 15px !important;
    line-height: 1.65 !important;
    max-width: none !important;
    width: 100% !important;
}

.pdf-turn-content > [data-message-author-role] {
    background: transparent !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-sizing: border-box !important;
    display: block !important;
    font-size: inherit !important;
    line-height: inherit !important;
    margin: 0 !important;
    max-width: none !important;
    padding: 0 !important;
    width: 100% !important;
}

/* 3. Use the printable page width instead of ChatGPT's narrow reading column */
main {
    --thread-content-max-width: 100% !important;
}

main [class*="group/turn-messages"],
main [data-message-author-role] {
    width: 100% !important;
    max-width: 100% !important;
}

#univflow-print-document [data-message-author-role] {
    box-sizing: border-box !important;
    margin: 0 0 24px !important;
    padding: 0 !important;
    border-radius: 0 !important;
    font-size: 15px !important;
    line-height: 1.65 !important;
    background: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
    break-inside: auto !important;
    page-break-inside: auto !important;
    orphans: 3;
    widows: 3;
}

#univflow-print-document [data-message-author-role="user"] {
    background: transparent !important;
}

#univflow-print-document [data-message-author-role="assistant"] {
    background: transparent !important;
}

/* Flatten copied site components so web-chat decoration cannot leak into print. */
#univflow-print-document *,
#univflow-print-document *::before,
#univflow-print-document *::after {
    box-shadow: none !important;
}

#univflow-print-document [data-message-author-role],
#univflow-print-document [data-message-author-role] * {
    background-image: none !important;
}

/* Expand the app's nested conversation scroller for complete print output */
body [class*="scroll-root"] {
    height: auto !important;
    max-height: none !important;
    min-height: max-content !important;
    overflow: visible !important;
    flex: none !important;
}

/* 4. Keep related blocks together without forcing whole long answers onto one page */
h1, h2, h3, h4, figure, table, pre, blockquote, li,
img, svg, canvas, [class*="artifact"] {
    break-inside: avoid !important;
    page-break-inside: avoid !important;
}

#univflow-print-document h1,
#univflow-print-document h2,
#univflow-print-document h3 {
    color: #172033 !important;
    line-height: 1.3 !important;
    margin-top: 1.2em !important;
    margin-bottom: 0.55em !important;
    break-after: avoid-page !important;
    page-break-after: avoid !important;
}

#univflow-print-document h1 { font-size: 1.65em !important; }
#univflow-print-document h2 { font-size: 1.35em !important; }
#univflow-print-document h3 { font-size: 1.15em !important; }

#univflow-print-document p,
#univflow-print-document ul,
#univflow-print-document ol,
#univflow-print-document blockquote {
    margin-top: 0.5em !important;
    margin-bottom: 0.75em !important;
}

#univflow-print-document table {
    width: 100% !important;
    border-collapse: collapse !important;
    font-size: 0.92em !important;
}

#univflow-print-document th,
#univflow-print-document td {
    border: 0 !important;
    border-bottom: 1px solid #d9dee8 !important;
    padding: 7px 9px !important;
    vertical-align: top !important;
}

#univflow-print-document th {
    background: transparent !important;
    font-weight: 650 !important;
}

/* 5. Code formatting & wrapping */
pre, code {
    white-space: pre-wrap !important;
    word-break: break-word !important;
    font-family: "JetBrains Mono", Consolas, Menlo, Monaco, monospace !important;
    font-size: 11.5px !important;
}

pre {
    background: transparent !important;
    border: 1px solid #d9dee8 !important;
    border-radius: 0 !important;
    padding: 10px 12px !important;
    margin: 12px 0 !important;
}

/* 6. Ensure high-fidelity color printing */
* {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
}

/* 7. Images and diagrams display */
img, svg, canvas {
    max-width: 100% !important;
    height: auto !important;
    display: block !important;
    margin: 12px auto !important;
}
"""


class WebChatPdfService:
    """Automates rendering and PDF compilation of web AI conversations."""

    @staticmethod
    def detect_platform(url: str) -> str:
        """Detect the source AI platform from URL."""
        netloc = urlparse(url).netloc.lower()
        if "chatgpt.com" in netloc or "openai.com" in netloc:
            return "chatgpt"
        if "claude.ai" in netloc:
            return "claude"
        if "gemini.google.com" in netloc or "g.co/gemini" in url:
            return "gemini"
        return "generic"

    @staticmethod
    def is_public_url(url: str) -> bool:
        """Check if the URL is a public shared snapshot (does not require login)."""
        lower = url.lower()
        if "/share/" in lower or "g.co/gemini/share" in lower:
            return True
        return False

    @classmethod
    async def _launch_browser(cls, playwright_instance):
        """Resiliently launch Chromium across container, Linux, and Windows hosts."""
        args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1280,900",
        ]
        # 1. Default bundled Chromium
        try:
            return await playwright_instance.chromium.launch(headless=True, args=args)
        except Exception as e:
            logger.info("Default Chromium launch skipped (%s), trying system channels", e)

        # 2. Edge channel (Windows / Dev)
        try:
            return await playwright_instance.chromium.launch(channel="msedge", headless=True, args=args)
        except Exception:
            pass

        # 3. Chrome channel
        try:
            return await playwright_instance.chromium.launch(channel="chrome", headless=True, args=args)
        except Exception:
            pass

        # Re-raise standard launch
        return await playwright_instance.chromium.launch(headless=True, args=args)

    @classmethod
    async def export_chat_to_pdf(
        cls,
        url: str,
        cookies: Optional[List[Dict[str, Any]]] = None,
        custom_title: Optional[str] = None,
        timeout_seconds: int = 90,
    ) -> Dict[str, Any]:
        """Load conversation in headless Chromium, render all turns & visual assets, and compile A4 PDF."""
        platform = cls.detect_platform(url)
        is_public = cls.is_public_url(url)
        logger.info("Starting web chat PDF export for %s (platform=%s, public=%s)", url, platform, is_public)

        async with async_playwright() as p:
            browser = await cls._launch_browser(p)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
            )

            # Inject session cookies if private URL and cookies provided
            if cookies and not is_public:
                try:
                    formatted_cookies = []
                    target_domain = urlparse(url).netloc
                    for c in cookies:
                        if isinstance(c, dict) and c.get("name") and c.get("value"):
                            domain = c.get("domain") or target_domain
                            if not domain.startswith(".") and not domain.startswith("http"):
                                domain = f".{domain}"
                            cookie_dict = {
                                "name": c["name"],
                                "value": c["value"],
                                "domain": domain,
                                "path": c.get("path", "/"),
                            }
                            formatted_cookies.append(cookie_dict)
                    if formatted_cookies:
                        await context.add_cookies(formatted_cookies)
                        logger.info("Injected %d session cookies for %s", len(formatted_cookies), target_domain)
                except Exception as e:
                    logger.warning("Could not inject session cookies: %s", e)

            page = await context.new_page()

            try:
                # 1. Navigate to chat page
                try:
                    await page.goto(url, wait_until="networkidle", timeout=min(timeout_seconds * 1000, 45000))
                except Exception:
                    # Fallback if networkidle takes longer than expected
                    await page.goto(url, wait_until="domcontentloaded", timeout=min(timeout_seconds * 1000, 30000))
                    await asyncio.sleep(4)

                # Check if page is 404 or expired
                page_text = (await page.content()).lower()
                if "conversation not found" in page_text or "404 not found" in page_text or "this link has expired" in page_text:
                    raise ValueError("This chat link is no longer accessible or has expired.")

                if platform == "chatgpt":
                    try:
                        await page.wait_for_selector(
                            "main [data-message-author-role]",
                            state="attached",
                            timeout=min(timeout_seconds * 1000, 45000),
                        )
                    except PlaywrightTimeoutError as exc:
                        raise ValueError(
                            "ChatGPT did not provide any exportable messages before the loading timeout."
                        ) from exc

                # 2. Automated incremental scroll to load 100% of virtualized / lazy-loaded turns
                await page.evaluate("""
                    async () => {
                        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                        const root = document.scrollingElement || document.documentElement || document.body;
                        const scrollable = [root, ...document.querySelectorAll('body *')]
                            .filter(node => {
                                const overflowY = getComputedStyle(node).overflowY;
                                return node.scrollHeight > node.clientHeight + 100
                                    && (node === root || overflowY === 'auto' || overflowY === 'scroll');
                            })
                            .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0];
                        const el = scrollable || root;

                        let stablePasses = 0;
                        let previousHeight = -1;
                        let previousCount = -1;
                        let attempts = 0;
                        while (stablePasses < 6 && attempts < 120) {
                            el.scrollTo(0, el.scrollHeight);
                            await sleep(400);

                            const height = el.scrollHeight;
                            const count = document.querySelectorAll('main [data-message-author-role]').length;
                            const atBottom = el.scrollTop + el.clientHeight >= height - 2;
                            if (atBottom && height === previousHeight && count === previousCount) {
                                stablePasses++;
                            } else {
                                stablePasses = 0;
                            }
                            previousHeight = height;
                            previousCount = count;
                            attempts++;
                        }

                        el.scrollTo(0, 0);
                        await sleep(500);
                    }
                """)

                # 3. Wait for all images (DALL-E, Gemini, uploads) and SVGs/canvas/artifacts to render
                await page.evaluate("""
                    async () => {
                        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                        const images = Array.from(document.querySelectorAll('img'));
                        await Promise.all(images.map(img => {
                            if (img.complete && img.naturalWidth > 0) return Promise.resolve();
                            return new Promise(resolve => {
                                img.addEventListener('load', resolve, { once: true });
                                img.addEventListener('error', resolve, { once: true });
                                setTimeout(resolve, 3000);
                            });
                        }));
                        await sleep(500);
                    }
                """)

                # 4. Extract conversation metadata
                raw_title = await page.title()
                clean_title = custom_title or raw_title.replace(" | ChatGPT", "").replace(" | Claude", "").replace(" - Gemini", "").strip()
                if not clean_title or clean_title.lower() in {"chatgpt", "claude", "gemini"}:
                    # Try getting from first H1 or first user message
                    try:
                        heading = await page.locator("h1").first.text_content(timeout=1000)
                        if heading and len(heading.strip()) > 3:
                            clean_title = heading.strip()
                    except Exception:
                        pass
                if not clean_title:
                    clean_title = f"{platform.capitalize()} Study Conversation"

                # Detect turns, images, and diagrams
                message_count = await page.locator("main [data-message-author-role]").count()
                turn_count = message_count or await page.locator('article, [class*="message"]').count()
                if turn_count == 0:
                    turn_count = 1  # Fallback minimum
                has_images = (await page.locator("img").count()) > 1
                has_diagrams = (await page.locator("svg, canvas, [class*='mermaid'], [class*='artifact']").count()) > 0

                # Render the actual message content outside the site's scroll-only app shell.
                print_turn_count = await page.evaluate(
                    """({title, platform}) => {
                        const messages = Array.from(
                            document.querySelectorAll('main [data-message-author-role]')
                        );
                        if (!messages.length) return 0;

                        const printable = document.createElement('main');
                        printable.id = 'univflow-print-document';
                        const titleBlock = document.createElement('div');
                        titleBlock.className = 'pdf-document-title';
                        const platformLabel = document.createElement('p');
                        platformLabel.textContent = `${platform} study conversation`;
                        const titleHeading = document.createElement('h1');
                        titleHeading.textContent = title;
                        titleBlock.append(platformLabel, titleHeading);
                        printable.append(titleBlock);

                        for (const message of messages) {
                            const role = message.getAttribute('data-message-author-role');
                            if (role !== 'user' && role !== 'assistant') continue;

                            const turn = document.createElement('section');
                            turn.className = `pdf-turn pdf-turn-${role}`;
                            const label = document.createElement('span');
                            label.className = 'pdf-turn-label';
                            label.textContent = role === 'user' ? 'You' : platform;

                            const content = document.createElement('div');
                            content.className = 'pdf-turn-content';
                            const copy = message.cloneNode(true);
                            copy.querySelectorAll(
                                'button, [role="toolbar"], [data-testid*="copy"]'
                            ).forEach(node => node.remove());

                            const sourceCanvases = message.querySelectorAll('canvas');
                            const copiedCanvases = copy.querySelectorAll('canvas');
                            for (let index = 0; index < sourceCanvases.length; index++) {
                                try {
                                    const image = document.createElement('img');
                                    image.src = sourceCanvases[index].toDataURL();
                                    image.alt = 'Conversation diagram';
                                    copiedCanvases[index].replaceWith(image);
                                } catch (error) {
                                    console.warn('Could not preserve a canvas in the PDF export.', error);
                                }
                            }

                            content.append(copy);
                            turn.append(label, content);
                            printable.append(turn);
                        }

                        document.body.append(printable);
                        return printable.querySelectorAll('.pdf-turn').length;
                    }""",
                    {"title": clean_title, "platform": platform.capitalize()},
                )
                if print_turn_count:
                    turn_count = print_turn_count
                elif platform == "chatgpt":
                    raise ValueError("The ChatGPT share page loaded without any exportable messages.")

                # 5. Inject clean academic print CSS
                await page.add_style_tag(content=PRINT_ENHANCEMENT_CSS)
                await asyncio.sleep(0.5)

                # 6. Generate A4 PDF with Chromium
                safe_doc_title = clean_title[:80].replace('"', "'")
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"},
                    display_header_footer=True,
                    header_template=f"""
                        <div style="font-size: 9px; color: #64748b; width: 100%; display: flex; justify-content: space-between; align-items: center; padding: 0 16mm 5px; border-bottom: 1px solid #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
                            <span style="font-weight: 600; letter-spacing: .04em;">UNIVFLOW STUDY ARCHIVE · {platform.upper()}</span>
                            <span style="max-width: 55%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;">{safe_doc_title}</span>
                        </div>
                    """,
                    footer_template="""
                        <div style="font-size: 9px; color: #64748b; width: 100%; display: flex; justify-content: center; padding-top: 5px; border-top: 1px solid #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
                            Page <span class="pageNumber" style="padding: 0 3px;"></span> of <span class="totalPages"></span>
                        </div>
                    """,
                )

                logger.info(
                    "PDF successfully compiled: %d bytes (title='%s', turns=%d, diagrams=%s, images=%s)",
                    len(pdf_bytes),
                    clean_title,
                    turn_count,
                    has_diagrams,
                    has_images,
                )

                return {
                    "pdf_bytes": pdf_bytes,
                    "title": clean_title,
                    "source_platform": platform,
                    "source_url": url,
                    "is_public": is_public,
                    "turn_count": turn_count,
                    "has_images": has_images,
                    "has_diagrams": has_diagrams,
                    "file_size_bytes": len(pdf_bytes),
                }

            finally:
                await context.close()
                await browser.close()
