"""Browser URL collectors for Windows using UI Automation."""

import logging
import subprocess

from capture.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class ChromeURLCollector(BaseCollector):
    """Gets the active Chrome tab URL via PowerShell + UI Automation."""

    event_type = "browser_url"
    source = "chrome"

    def __init__(self):
        self._last_url = ""

    def collect(self) -> list[str]:
        try:
            # Use PowerShell to get Chrome URL via UI Automation
            ps_script = (
                '$p = Get-Process chrome -ErrorAction SilentlyContinue | '
                'Where-Object { $_.MainWindowTitle -ne "" } | Select-Object -First 1; '
                'if ($p) { '
                '  Add-Type -AssemblyName UIAutomationClient; '
                '  $root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle); '
                '  $cond = New-Object System.Windows.Automation.PropertyCondition('
                '    [System.Windows.Automation.AutomationElement]::ControlTypeProperty, '
                '    [System.Windows.Automation.ControlType]::Edit); '
                '  $bar = $root.FindFirst("Descendants", $cond); '
                '  if ($bar) { '
                '    $val = $bar.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); '
                '    Write-Output $val.Current.Value '
                '  } '
                '}'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=5,
            )
            url = result.stdout.strip()
            if not url or url == self._last_url:
                return []

            self._last_url = url
            logger.debug("chrome: %s", url)
            return [url]

        except subprocess.TimeoutExpired:
            return []
        except Exception:
            logger.debug("chrome: not running or not accessible")
            return []


class EdgeURLCollector(BaseCollector):
    """Gets the active Edge tab URL via PowerShell + UI Automation."""

    event_type = "browser_url"
    source = "edge"

    def __init__(self):
        self._last_url = ""

    def collect(self) -> list[str]:
        try:
            ps_script = (
                '$p = Get-Process msedge -ErrorAction SilentlyContinue | '
                'Where-Object { $_.MainWindowTitle -ne "" } | Select-Object -First 1; '
                'if ($p) { '
                '  Add-Type -AssemblyName UIAutomationClient; '
                '  $root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle); '
                '  $cond = New-Object System.Windows.Automation.PropertyCondition('
                '    [System.Windows.Automation.AutomationElement]::ControlTypeProperty, '
                '    [System.Windows.Automation.ControlType]::Edit); '
                '  $bar = $root.FindFirst("Descendants", $cond); '
                '  if ($bar) { '
                '    $val = $bar.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); '
                '    Write-Output $val.Current.Value '
                '  } '
                '}'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=5,
            )
            url = result.stdout.strip()
            if not url or url == self._last_url:
                return []

            self._last_url = url
            logger.debug("edge: %s", url)
            return [url]

        except subprocess.TimeoutExpired:
            return []
        except Exception:
            logger.debug("edge: not running or not accessible")
            return []


COLLECTORS = [
    ("win32", ChromeURLCollector),
    ("win32", EdgeURLCollector),
]
