# Log the current mouse cursor handle, without injecting anything.
#
# Used to identify which handle belongs to which drag cursor:
#   run it, drag a file across drives WITHOUT holding Shift  -> that handle = COPY
#   run it, drag a file across drives WHILE holding Shift    -> that handle = MOVE
# Then compare with the handle you saw when the overlay injected its modifier.
#
# Usage:
#   .\cursor-log.ps1 -Seconds 12
#
# Drag across drives (D: -> C:) during the whole countdown.

param(
    [int]$Seconds = 12,
    [int]$IntervalMs = 500
)

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class CursorProbe
{
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

    [DllImport("user32.dll")]
    public static extern bool GetCursorInfo(ref CURSORINFO pci);

    [DllImport("user32.dll")]
    public static extern short GetAsyncKeyState(int vKey);

    public static string Current()
    {
        CURSORINFO info = new CURSORINFO();
        info.cbSize = Marshal.SizeOf(typeof(CURSORINFO));

        if (!GetCursorInfo(ref info)) { return "n/a"; }

        return "0x" + info.hCursor.ToInt64().ToString("X");
    }
}
'@

'--- Start dragging a file across drives now ---'
'--- First WITHOUT Shift, then with the PHYSICAL Shift key held ---'
''

$stop = (Get-Date).AddSeconds($Seconds)

while ((Get-Date) -lt $stop) {

    $shift = [CursorProbe]::GetAsyncKeyState(0x10)
    $shiftText = 'up'
    if (($shift -band 0x8000) -ne 0) { $shiftText = 'DOWN' }

    '{0}  cursor={1,-12} shift={2}' -f (Get-Date -Format 'HH:mm:ss'), [CursorProbe]::Current(), $shiftText

    Start-Sleep -Milliseconds $IntervalMs
}

''
'--- done ---'
