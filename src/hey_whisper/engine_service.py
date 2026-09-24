"""Keeps a `hey-whisper --serve-socket` engine running for other apps (Joplin).

Turning it on starts the engine now and at every login; turning it off stops
it and removes the login item. Inside the Flatpak the login item is requested
through the Background portal (which writes the autostart file for us), and
the engine is started through the Flatpak portal's Spawn in a sandbox of its
own, so it doesn't die with the GUI's. Outside Flatpak both are done directly.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from hey_whisper import serve

APP_ID = "org.heywhisper.HeyWhisper"
ENGINE_ARGS = ["--serve-socket"]
START_TIMEOUT = 30.0  # Importing the audio/ML stack can take a while on a cold start
PORTAL_TIMEOUT = 120.0  # The portal may be waiting for the user to answer a prompt


def in_flatpak() -> bool:
    return Path("/.flatpak-info").exists()


def autostart_file() -> Path:
    if in_flatpak():
        # Written by the portal on the host, so it lands in the host's
        # ~/.config, not the $XDG_CONFIG_HOME Flatpak gives the app.
        return Path.home() / ".config" / "autostart" / f"{APP_ID}.desktop"
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_home / "autostart" / f"{APP_ID}-engine.desktop"


def log_file() -> Path:
    return serve.default_socket_path().parent / "engine.log"


def autostart_enabled() -> bool:
    try:
        return "--serve-socket" in autostart_file().read_text(encoding="utf-8")
    except OSError:
        return False


def engine_running() -> bool:
    return serve._engine_listening(serve.default_socket_path())


def _desktop_exec_quote(arg: str) -> str:
    # Quoting rules from the Desktop Entry spec's Exec key
    if arg and not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    escaped = "".join("\\" + c if c in '"`$\\' else c for c in arg)
    return f'"{escaped}"'


def _host_engine_argv() -> list:
    return [sys.executable, "-m", "hey_whisper.main", *ENGINE_ARGS]


def _write_autostart_file(enabled: bool) -> None:
    path = autostart_file()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Hey Whisper engine\n"
        "Comment=Keeps the Hey Whisper engine running for Joplin\n"
        f"Exec={' '.join(_desktop_exec_quote(a) for a in _host_engine_argv())}\n"
        "Icon=org.heywhisper.HeyWhisper\n"
        "NoDisplay=true\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


async def _request_background(autostart: bool) -> None:
    """Ask org.freedesktop.portal.Background to add or remove our login item."""
    from dbus_next import Message, MessageType, Variant
    from dbus_next.aio import MessageBus

    bus = await MessageBus().connect()
    try:
        token = f"hey_whisper_{uuid.uuid4().hex}"
        sender = bus.unique_name.lstrip(":").replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        response = asyncio.get_running_loop().create_future()

        def on_message(msg):
            if msg.path == handle and msg.member == "Response" and not response.done():
                response.set_result(msg.body)

        bus.add_message_handler(on_message)
        # Subscribe before calling, or a quick reply could arrive unseen
        await bus.call(Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="AddMatch",
            signature="s",
            body=[f"type='signal',interface='org.freedesktop.portal.Request',member='Response',path='{handle}'"],
        ))
        reply = await bus.call(Message(
            destination="org.freedesktop.portal.Desktop",
            path="/org/freedesktop/portal/desktop",
            interface="org.freedesktop.portal.Background",
            member="RequestBackground",
            signature="sa{sv}",
            body=["", {
                "handle_token": Variant("s", token),
                "reason": Variant("s", "Keep the speech engine running so Joplin can use it."),
                "autostart": Variant("b", autostart),
                "commandline": Variant("as", ["hey-whisper", *ENGINE_ARGS]),
            }],
        ))
        if reply.message_type == MessageType.ERROR:
            detail = reply.body[0] if reply.body else reply.error_name
            raise RuntimeError(f"The background portal is unavailable: {detail}")

        code, results = await asyncio.wait_for(response, PORTAL_TIMEOUT)
        if code != 0:
            raise RuntimeError("Running in the background was not allowed.")
        granted = results.get("autostart")
        if autostart and not (granted and granted.value):
            raise RuntimeError("The system did not allow Hey Whisper to start at login.")
    finally:
        bus.disconnect()


async def _portal_spawn(argv: list, out_fd: int, env: Optional[dict] = None) -> int:
    """Start argv in a new sandbox of this app via org.freedesktop.portal.Flatpak.

    Unlike the `flatpak-spawn` tool, which stays running to relay the child's
    exit status (and so keeps this sandbox alive after the window closes),
    this returns as soon as the process has started.
    """
    from dbus_next import Message, MessageType, Variant
    from dbus_next.aio import MessageBus

    bus = await MessageBus(negotiate_unix_fd=True).connect()
    try:
        stdin = os.open(os.devnull, os.O_RDONLY)
        try:
            reply = await bus.call(Message(
                destination="org.freedesktop.portal.Flatpak",
                path="/org/freedesktop/portal/Flatpak",
                interface="org.freedesktop.portal.Flatpak",
                member="Spawn",
                signature="ayaaya{uh}a{ss}ua{sv}",
                body=[
                    b"/\0",
                    [a.encode() + b"\0" for a in argv],
                    {0: 0, 1: 1, 2: 1},  # child fd -> index into unix_fds
                    env or {},
                    0,  # No flags: not tied to our D-Bus connection, so it outlives us
                    {},
                ],
                unix_fds=[stdin, out_fd],
            ))
        finally:
            os.close(stdin)
        if reply.message_type == MessageType.ERROR:
            detail = reply.body[0] if reply.body else reply.error_name
            raise RuntimeError(f"Could not start the engine: {detail}")
        return reply.body[0]
    finally:
        bus.disconnect()


def set_autostart(enabled: bool) -> None:
    if in_flatpak():
        asyncio.run(_request_background(enabled))
    else:
        _write_autostart_file(enabled)


def start_engine() -> None:
    """Start the engine in the background (if it isn't already) and wait for its socket."""
    if engine_running():
        return
    log = log_file()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        if in_flatpak():
            # A plain child would be killed along with this sandbox when the window closes
            asyncio.run(_portal_spawn(["hey-whisper", *ENGINE_ARGS], out.fileno()))
        else:
            subprocess.Popen(
                _host_engine_argv(), stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True,
            )

    deadline = time.monotonic() + START_TIMEOUT
    while not engine_running():
        if time.monotonic() > deadline:
            raise RuntimeError(f"The engine did not start. See {log}")
        time.sleep(0.2)


def stop_engine() -> None:
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        conn.connect(str(serve.default_socket_path()))
        conn.sendall((json.dumps({"cmd": "shutdown"}) + "\n").encode())
    except OSError:
        pass  # Not running
    finally:
        conn.close()


def enable() -> None:
    set_autostart(True)
    start_engine()


def disable() -> None:
    set_autostart(False)
    stop_engine()
