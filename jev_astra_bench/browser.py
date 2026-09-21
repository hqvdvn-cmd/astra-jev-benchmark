from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True, frozen=True)
class BrowserSnapshot:
    state: str
    candidates: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class BrowserChoice:
    operation: str
    target: str
    value: str | None = None

    def encoded(self) -> str:
        return f"{self.operation}:{self.target}"


@dataclass(slots=True, frozen=True)
class BrowserResult:
    success: bool
    state: str
    error: str | None = None


class BrowserAdapter(Protocol):
    def snapshot(self) -> BrowserSnapshot: ...
    def perform(self, choice: BrowserChoice) -> BrowserResult: ...
    def reset(self) -> None: ...


class FakeBrowserAdapter:
    """Deterministic adapter used by tests and the no-network canary."""

    def __init__(self) -> None:
        self._state = "form_ready"
        self._allowed = {
            "fill:email": "email_filled",
            "click:submit": "submitted",
            "wait:ready": "form_ready",
            "stop:done": "done",
        }

    def snapshot(self) -> BrowserSnapshot:
        if self._state == "submitted":
            candidates = ("stop:done",)
        elif self._state == "email_filled":
            candidates = ("click:submit", "fill:email")
        else:
            candidates = ("fill:email",)
        return BrowserSnapshot(
            f"state={self._state};email_filled={self._state == 'email_filled'}",
            candidates,
        )

    def perform(self, choice: BrowserChoice) -> BrowserResult:
        encoded = choice.encoded()
        if encoded not in self._allowed:
            return BrowserResult(False, self.snapshot().state, "choice_not_allowed")
        if encoded == "click:submit" and self._state != "email_filled":
            return BrowserResult(False, self.snapshot().state, "email_required")
        self._state = self._allowed[encoded]
        return BrowserResult(True, self.snapshot().state)

    def reset(self) -> None:
        self._state = "form_ready"


class PlaywrightBrowserAdapter:
    def __init__(self, page: object | None = None) -> None:
        if page is None:
            raise RuntimeError("Playwright browser page is not configured; use preflight before a live browser run")
        self.page = page

    def snapshot(self) -> BrowserSnapshot:
        state = self.page.locator("#state").inner_text()
        email = self.page.locator("#email").input_value()
        if state == "submitted":
            candidates = ("stop:done",)
        elif email:
            candidates = ("click:submit", "fill:email")
        else:
            candidates = ("fill:email",)
        return BrowserSnapshot(f"state={state};email_filled={bool(email)}", candidates)

    def perform(self, choice: BrowserChoice) -> BrowserResult:
        allowed = self.snapshot().candidates
        if choice.encoded() not in allowed:
            return BrowserResult(False, self.snapshot().state, "choice_not_allowed")
        try:
            if choice.operation == "fill" and choice.target == "email":
                if not choice.value:
                    return BrowserResult(False, self.snapshot().state, "value_required")
                self.page.locator("#email").fill(choice.value)
            elif choice.operation == "click" and choice.target == "submit":
                self.page.locator("#submit").click()
            elif choice.operation == "stop" and choice.target == "done":
                pass
            else:
                return BrowserResult(False, self.snapshot().state, "choice_not_allowed")
        except Exception as error:
            return BrowserResult(False, self.snapshot().state, type(error).__name__)
        return BrowserResult(True, self.snapshot().state)

    def reset(self) -> None:
        self.page.reload()


class LocalPlaywrightSession:
    def __init__(self, page_path: Path) -> None:
        self.page_path = page_path
        self._manager = None
        self._browser = None

    def __enter__(self) -> PlaywrightBrowserAdapter:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError("Playwright is not installed") from error
        self._manager = sync_playwright().start()
        self._browser = self._manager.chromium.launch(headless=True)
        page = self._browser.new_page()
        page.goto(self.page_path.resolve().as_uri())
        return PlaywrightBrowserAdapter(page)

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._manager is not None:
            self._manager.stop()
