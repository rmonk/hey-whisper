"""XDG Desktop Portal Global Shortcuts integration for Wayland, Flatpak, and Linux."""

import asyncio
import logging
import os
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

try:
    from dbus_next.aio import MessageBus
    from dbus_next import Message, Variant
    HAS_DBUS_NEXT = True
except ImportError:
    HAS_DBUS_NEXT = False

logger = logging.getLogger(__name__)


class PortalShortcutsManager(QObject):
    """Manages system-wide global shortcuts via org.freedesktop.portal.GlobalShortcuts."""

    shortcut_activated = pyqtSignal(str)
    shortcut_deactivated = pyqtSignal(str)
    portal_ready = pyqtSignal(bool, str)  # (success, trigger_description)

    def __init__(self, parent=None, preferred_trigger: str = "Ctrl+Alt+R"):
        super().__init__(parent)
        self.preferred_trigger = preferred_trigger
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._bus: Optional[MessageBus] = None
        self._session_handle: Optional[str] = None
        self._is_running = False

    def start(self):
        """Start global shortcuts listener thread."""
        if not HAS_DBUS_NEXT:
            logger.warning("dbus-next is not installed; global portal shortcuts disabled.")
            self.portal_ready.emit(False, "dbus-next missing")
            return

        if os.environ.get("CI") or os.environ.get("HEY_WHISPER_NO_PORTAL") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            logger.info("Headless / CI environment detected; portal shortcuts disabled.")
            self.portal_ready.emit(False, "portal disabled in test/CI")
            return

        self._is_running = True
        self._thread = threading.Thread(target=self._run_loop, name="GlobalShortcutsPortalThread", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop global shortcuts listener thread."""
        self._is_running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive() and threading.current_thread() != self._thread:
            self._thread.join(timeout=0.5)

    def configure_shortcuts(self):
        """Open system desktop shortcut configuration dialog."""
        if not self._loop or not self._session_handle:
            logger.info("Cannot configure shortcuts: session not active.")
            return

        asyncio.run_coroutine_threadsafe(self._do_configure(), self._loop)


    def _run_loop(self):
        """Worker thread entry point."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._setup_portal())
            self._loop.run_forever()
        except Exception as e:
            logger.warning("Global shortcuts portal loop error: %s", e)
            self.portal_ready.emit(False, str(e))
        finally:
            if self._bus:
                try:
                    self._bus.disconnect()
                except Exception:
                    pass
            self._loop.close()

    async def _setup_portal(self):
        """Initialize session and bind shortcut with XDG Desktop Portal."""
        try:
            self._bus = await MessageBus().connect()

            # Subscribe to signals from portal
            await self._bus.call(Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=["type='signal',interface='org.freedesktop.portal.GlobalShortcuts'"],
            ))

            session_fut = self._loop.create_future()
            bind_fut = self._loop.create_future()

            def on_message(msg: Message):
                # Request response handling
                if msg.interface == "org.freedesktop.portal.Request" and msg.member == "Response":
                    if len(msg.body) >= 2 and isinstance(msg.body[1], dict):
                        resp_dict = msg.body[1]
                        if "session_handle" in resp_dict and not session_fut.done():
                            session_fut.set_result(resp_dict["session_handle"].value)
                        elif "shortcuts" in resp_dict and not bind_fut.done():
                            bind_fut.set_result(resp_dict["shortcuts"].value)

                # Portal global shortcut signals
                elif msg.interface == "org.freedesktop.portal.GlobalShortcuts" and self._is_running:
                    if msg.member == "Activated" and len(msg.body) >= 2:
                        shortcut_id = str(msg.body[1])
                        self.shortcut_activated.emit(shortcut_id)
                    elif msg.member == "Deactivated" and len(msg.body) >= 2:
                        shortcut_id = str(msg.body[1])
                        self.shortcut_deactivated.emit(shortcut_id)

            self._bus.add_message_handler(on_message)

            # Step 1: CreateSession
            msg_create = Message(
                destination="org.freedesktop.portal.Desktop",
                path="/org/freedesktop/portal/desktop",
                interface="org.freedesktop.portal.GlobalShortcuts",
                member="CreateSession",
                signature="a{sv}",
                body=[{
                    "session_handle_token": Variant("s", "hey_whisper_session"),
                    "handle_token": Variant("s", "req_create_session"),
                }],
            )
            await asyncio.wait_for(self._bus.call(msg_create), timeout=3.0)
            self._session_handle = await asyncio.wait_for(session_fut, timeout=3.0)

            # Step 2: BindShortcuts
            msg_bind = Message(
                destination="org.freedesktop.portal.Desktop",
                path="/org/freedesktop/portal/desktop",
                interface="org.freedesktop.portal.GlobalShortcuts",
                member="BindShortcuts",
                signature="oa(sa{sv})sa{sv}",
                body=[
                    self._session_handle,
                    [
                        ["record_voice_note", {
                            "description": Variant("s", "Hey Whisper: Record Voice Note (Hold or Toggle)"),
                            "preferred_trigger": Variant("s", self.preferred_trigger),
                        }],
                    ],
                    "",
                    {"handle_token": Variant("s", "req_bind_shortcuts")},
                ],
            )
            await asyncio.wait_for(self._bus.call(msg_bind), timeout=3.0)

            trigger_info = self.preferred_trigger
            try:
                shortcuts = await asyncio.wait_for(bind_fut, timeout=3.0)
                if shortcuts:
                    opts = shortcuts[0][1]
                    if "trigger_description" in opts:
                        val = opts["trigger_description"].value
                        if val:
                            trigger_info = val
            except Exception:
                pass

            self.portal_ready.emit(True, trigger_info)

        except Exception as e:
            logger.info("Global shortcuts portal not active or unsupported: %s", e)
            self.portal_ready.emit(False, str(e))

    async def _do_configure(self):
        """Invoke ConfigureShortcuts on desktop portal."""
        if not self._bus or not self._session_handle:
            return
        try:
            msg_conf = Message(
                destination="org.freedesktop.portal.Desktop",
                path="/org/freedesktop/portal/desktop",
                interface="org.freedesktop.portal.GlobalShortcuts",
                member="ConfigureShortcuts",
                signature="osa{sv}",
                body=[
                    self._session_handle,
                    "",
                    {"handle_token": Variant("s", "req_configure_shortcuts")},
                ],
            )
            await self._bus.call(msg_conf)
        except Exception as e:
            logger.warning("ConfigureShortcuts error: %s", e)
