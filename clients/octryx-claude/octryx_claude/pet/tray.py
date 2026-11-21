"""The tray icon (pystray): image, tooltip, menu and notifications, driven by :class:`runner.Runner`.

macOS details pystray leaves open, handled here:

- AppKit is touched only on the main thread: the poll loop runs in pystray's setup thread and hands every change
  to the main thread (``PyObjCTools.AppHelper.callAfter``);
- the image is drawn at the menu bar's pixel size (44 px on Retina) and given its point size, instead of pystray's
  own downscale to points, which blurs it;
- the mascot's colour follows the status item's appearance (light or dark menu bar), checked at every redraw;
- the process is an accessory app: no Dock icon, no app menu.

Windows (native, ``pythonw``): pystray's win32 backend; changes are applied directly (pystray posts them to its
window thread); the mascot's colour follows the taskbar (``SystemUsesLightTheme``), dark by default.
"""

from __future__ import annotations

import io
import logging
import sys
import webbrowser
from collections.abc import Callable
from typing import Any

from .display import Display, Notification
from .icons import render
from .runner import Runner

logger = logging.getLogger("octryx_claude.pet")
MACOS = sys.platform == "darwin"


def windows_appearance() -> str:
    """``light`` or ``dark`` for the Windows taskbar (``SystemUsesLightTheme``); dark when it cannot be read."""
    try:
        import winreg  # noqa: PLC0415

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return "light" if winreg.QueryValueEx(key, "SystemUsesLightTheme")[0] else "dark"
    except (ImportError, OSError):
        return "dark"


def _on_main(func: Callable[[], None]) -> None:
    if MACOS:
        from PyObjCTools import AppHelper  # noqa: PLC0415

        AppHelper.callAfter(func)
    else:
        func()


def _icon_class() -> type:
    import pystray  # noqa: PLC0415

    if not MACOS:
        return pystray.Icon

    import AppKit  # noqa: PLC0415
    import Foundation  # noqa: PLC0415

    class RetinaIcon(pystray.Icon):  # type: ignore[misc, valid-type]
        """pystray's macOS icon, drawn by the pet itself at the screen's pixel size and appearance."""

        pet_display: Display | None = None

        def _appearance(self) -> str:
            try:
                best = self._status_item.button().effectiveAppearance().bestMatchFromAppearancesWithNames_(
                    [AppKit.NSAppearanceNameAqua, AppKit.NSAppearanceNameDarkAqua])
            except Exception:  # noqa: BLE001 - an old macOS without appearances: a light bar
                return "light"
            return "dark" if best == AppKit.NSAppearanceNameDarkAqua else "light"

        def _assert_image(self) -> None:
            points = int(self._status_bar.thickness()) or 22
            screen = AppKit.NSScreen.mainScreen()
            scale = float(screen.backingScaleFactor()) if screen is not None else 2.0
            display = self.pet_display
            image = render(display.status if display else "resting", display.count if display else 0,
                           size=round(points * scale), appearance=self._appearance())
            buffer = io.BytesIO()
            image.save(buffer, "png")
            nsimage = AppKit.NSImage.alloc().initWithData_(Foundation.NSData(buffer.getvalue()))
            nsimage.setSize_((points, points))
            self._icon_image = nsimage
            self._status_item.button().setImage_(nsimage)

    return RetinaIcon


class Tray:
    def __init__(self, runner_factory: Callable[[Tray], Runner]) -> None:
        import pystray  # noqa: PLC0415

        self._pystray = pystray
        self.runner = runner_factory(self)
        self.current = self.runner.display()
        self.turned_off = False  # "Turn off Octryx": `pet run` turns the autostart off once the icon is gone
        icon_class = _icon_class()
        self.icon = icon_class("octryx", render("resting", size=64), "Octryx",
                               menu=pystray.Menu(self._menu_items))
        if MACOS:
            self.icon.pet_display = self.current

    # --- View for the runner (called from the poll thread) -------------------------------------------------

    def show(self, display: Display) -> None:
        self.current = display

        def apply() -> None:
            if MACOS:
                self.icon.pet_display = display
                self.icon._icon_image = None  # noqa: SLF001 - redraw at the next assert
                self.icon._assert_image()  # noqa: SLF001
            else:
                self.icon.icon = render(display.status, display.count, size=64, appearance=windows_appearance())
            self.icon.title = display.tooltip[:127]
            self.icon.update_menu()

        _on_main(apply)

    def notify(self, notification: Notification) -> None:
        # macOS: from octryx's own applet, so it shows as "Octryx" (pystray's osascript shows "Script Editor");
        # Windows: pystray's balloon. The title must be a str.
        if sys.platform == "darwin":
            from ..mac_notify import notify  # noqa: PLC0415

            notify(notification.title[:80] or "Octryx", notification.message[:200])
            return
        self.icon.notify(notification.message[:200], notification.title[:80])

    # --- menu -------------------------------------------------------------------------------------------------

    def _open(self, url: str | None) -> Callable[[Any, Any], None]:
        def action(_icon: Any, _item: Any) -> None:
            target = self.runner.link(url)
            if target:
                webbrowser.open(target)

        return action

    def _menu_items(self) -> list[Any]:
        item, separator = self._pystray.MenuItem, self._pystray.Menu.SEPARATOR
        display = self.current
        entries: list[Any] = [item(display.header, None, enabled=False)]
        entries += [item(f"  {entry.title or entry.kind}", self._open(entry.url), enabled=bool(entry.url))
                    for entry in display.items]
        entries += [separator, item("Open companion", self._open(display.panel_url)),
                    item("Connect iPhone…", lambda _i, _m: self._connect_phone())]
        quiet = self.runner.quiet_hours()
        entries += [
            item("Pause notifications for 1 hour", self._act(lambda: self.runner.pause(0 if self.runner.paused()
                                                                                      else 1)),
                 checked=lambda _m: self.runner.paused()),
            item(f"Quiet hours {quiet.label()}" if quiet.enabled else "Quiet hours: off",
                 self._act(self.runner.toggle_quiet_hours),
                 checked=lambda _m: self.runner.quiet_hours().enabled),
            item("Refresh now", self._act(self.runner.refresh_now)),
            separator,
            item("Turn off Octryx (also at login)", lambda _i, _m: self.turn_off()),
            item("Quit Octryx", lambda _i, _m: self.quit()),
        ]
        return entries

    def _connect_phone(self) -> None:
        from .connect import open_pairing  # noqa: PLC0415

        try:
            open_pairing(self.runner.account.root)
        except OSError:
            logger.warning("could not open the pairing terminal")

    @staticmethod
    def _act(func: Callable[[], None]) -> Callable[[Any, Any], None]:
        """A menu action; the menu is rebuilt after it (pystray's macOS backend does not), so checks follow."""

        def action(icon: Any, _item: Any) -> None:
            func()
            icon.update_menu()

        return action

    # --- lifecycle --------------------------------------------------------------------------------------------

    def _setup(self, icon: Any) -> None:
        icon.visible = True
        self.runner.loop()

    def run(self) -> None:
        if MACOS:
            import AppKit  # noqa: PLC0415

            AppKit.NSApplication.sharedApplication().setActivationPolicy_(
                AppKit.NSApplicationActivationPolicyAccessory)
        self.icon.run(setup=self._setup)

    def quit(self) -> None:
        self.runner.stop()
        self.icon.stop()

    def turn_off(self) -> None:
        """Quit, and do not come back at login until ``pet enable`` (the caller of :meth:`run` turns it off)."""
        self.turned_off = True
        self.quit()


__all__ = ["Tray"]
