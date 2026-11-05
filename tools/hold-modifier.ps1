# Hold a modifier key down with SendInput after an optional delay, and log the
# current mouse cursor handle once per second.
#
# Why: SUPERSTRIKE Overlay presses its modifier AFTER the mouse button went down
# (light press = click, deep press = modifier). This script reproduces that
# timing so we can see whether Explorer honours a modifier that arrives in the
# MIDDLE of a drag (physical Shift in the middle of a drag does change the
# cursor; the question is whether an injected one does too).
#
# The cursor handle column is the objective evidence: if the handle changes at
# the moment the modifier is injected, Explorer reacted; if it never changes,
# Explorer ignored the injected key.
#
# Usage:
#   .\hold-modifier.ps1                                   # hold Shift 15s, no delay
#   .\hold-modifier.ps1 -Key Shift -Delay 5 -Seconds 12    # wait 5s, then hold 12s
#   .\hold-modifier.ps1 -Key Ctrl -Delay 5 -Seconds 12
#
# Do this: start dragging a file across drives (D: -> C:), keep the mouse button
# down, and watch the countdown plus the cursor. The key is always released at
# the end, even on Ctrl+C.

param(
    [ValidateSet('Shift', 'Ctrl', 'Alt')]
    [string]$Key = 'Shift',

    [int]$Delay = 0,

    [int]$Seconds = 15
)

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class NativeInput
{
    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT
    {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT
    {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct INPUTUNION
    {
        [FieldOffset(0)] public KEYBDINPUT ki;
        [FieldOffset(0)] public MOUSEINPUT mi;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT
    {
        public uint type;
        public INPUTUNION u;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct CURSORINFO
    {
        public int cbSize;
        public int flags;
        public IntPtr hCursor;
        public POINT ptScreenPos;
    }

    public const uint INPUT_KEYBOARD = 1;
    public const uint KEYEVENTF_KEYUP = 0x0002;

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll")]
    public static extern short GetAsyncKeyState(int vKey);

    [DllImport("user32.dll")]
    public static extern bool GetCursorInfo(ref CURSORINFO pci);

    public static bool SetKey(ushort vk, bool down)
    {
        INPUT input = new INPUT();
        input.type = INPUT_KEYBOARD;
        input.u.ki.wVk = vk;
        input.u.ki.wScan = 0;
        input.u.ki.dwFlags = down ? 0u : KEYEVENTF_KEYUP;
        input.u.ki.time = 0;
        input.u.ki.dwExtraInfo = IntPtr.Zero;

        INPUT[] inputs = new INPUT[1];
        inputs[0] = input;

        uint sent = SendInput(1, inputs, (int)Marshal.SizeOf(typeof(INPUT)));
        return sent == 1;
    }

    public static string CursorHandle()
    {
        CURSORINFO info = new CURSORINFO();
        info.cbSize = Marshal.SizeOf(typeof(CURSORINFO));

        if (!GetCursorInfo(ref info)) { return "n/a"; }

        return "0x" + info.hCursor.ToInt64().ToString("X");
    }
}
'@

$VK = @{ Shift = 0x10; Ctrl = 0x11; Alt = 0x12 }
$vk = [uint16]$VK[$Key]

function Show-KeyState {
    param([string]$When)

    $state = [NativeInput]::GetAsyncKeyState([int]$vk)
    $held = (($state -band 0x8000) -ne 0)
    $verdict = 'NOT HELD'
    if ($held) { $verdict = 'HELD' }

    '  [{0,-11}] GetAsyncKeyState(0x{1:X2}) = 0x{2:X4} -> {3}' -f $When, $vk, ($state -band 0xFFFF), $verdict
}

try {
    if ($Delay -gt 0) {
        '--- START DRAGGING NOW. {0} second delay before {1} is pressed ---' -f $Delay, $Key
        for ($i = $Delay; $i -gt 0; $i--) {
            '  delay {0,3}s  cursor={1}' -f $i, [NativeInput]::CursorHandle()
            Start-Sleep -Seconds 1
        }
    }

    '--- SendInput: {0} DOWN (should happen while you are still dragging) ---' -f $Key
    $ok = [NativeInput]::SetKey($vk, $true)
    $sentText = '0 (FAILED)'
    if ($ok) { $sentText = '1 (OK)' }
    '  SendInput returned: {0}' -f $sentText

    Start-Sleep -Milliseconds 120
    Show-KeyState -When 'after down'
    '  cursor after {0} DOWN = {1}' -f $Key, [NativeInput]::CursorHandle()

    for ($i = $Seconds; $i -gt 0; $i--) {
        $state = [NativeInput]::GetAsyncKeyState([int]$vk)
        $heldText = 'up'
        if (($state -band 0x8000) -ne 0) { $heldText = 'DOWN' }

        '  hold {0,3}s  cursor={1,-12} {2}={3}' -f $i, [NativeInput]::CursorHandle(), $Key, $heldText
        Start-Sleep -Seconds 1
    }
}
finally {
    $null = [NativeInput]::SetKey($vk, $false)
    Start-Sleep -Milliseconds 120
    '--- SendInput: {0} UP ---' -f $Key
    Show-KeyState -When 'after up'
    '  cursor after {0} UP   = {1}' -f $Key, [NativeInput]::CursorHandle()
}
