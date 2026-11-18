"""Best-effort desktop notification: never blocking, never fatal.

The report and the line in logs/carmeta-sync.log are the reliable trace; this
is only the tap on the shoulder. Any failure — no desktop session, a locked
screen, a missing tool — is swallowed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

TIMEOUT_SECONDS = 10

# Title and body travel through the environment, never through the script
# text: a tag name must not be able to become PowerShell.
_WINDOWS_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$kind = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($kind)
$texts = $xml.GetElementsByTagName('text')
$texts.Item(0).AppendChild($xml.CreateTextNode($env:CARMETA_TITLE)) | Out-Null
$texts.Item(1).AppendChild($xml.CreateTextNode($env:CARMETA_BODY)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('cartometa-carmeta').Show($toast)
"""


def notify(title: str, body: str) -> bool:
    """Show a system notification; True when the command ran and succeeded."""
    try:
        if sys.platform == "darwin":
            # AppleScript string literals take the same escapes as JSON's.
            script = (f"display notification {json.dumps(body, ensure_ascii=False)} "
                      f"with title {json.dumps(title, ensure_ascii=False)}")
            command, env = ["osascript", "-e", script], None
        elif sys.platform == "win32":
            command = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                       _WINDOWS_TOAST]
            env = {**os.environ, "CARMETA_TITLE": title, "CARMETA_BODY": body}
        else:
            command, env = ["notify-send", title, body], None
        done = subprocess.run(command, env=env, timeout=TIMEOUT_SECONDS,
                              capture_output=True, check=False)
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
