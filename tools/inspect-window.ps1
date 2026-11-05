# Inspect the overlay's top-level window: extended styles (topmost / transparent /
# layered) plus WindowFromPoint results, to check whether the overlay can steal
# drag-and-drop hit testing.
#
# Usage: powershell -ExecutionPolicy Bypass -File .\inspect-window.ps1

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class WinInspect
{
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X; public int Y; }

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetClassName(IntPtr hWnd, StringBuilder name, int max);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int max);

    [DllImport("user32.dll")]
    public static extern IntPtr GetWindowLongPtr(IntPtr hWnd, int index);

    [DllImport("user32.dll")]
    public static extern IntPtr WindowFromPoint(POINT p);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);

    public static List<IntPtr> Collect()
    {
        List<IntPtr> result = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr l) { result.Add(h); return true; }, IntPtr.Zero);
        return result;
    }

    public static string ClassOf(IntPtr h)
    {
        StringBuilder sb = new StringBuilder(256);
        GetClassName(h, sb, sb.Capacity);
        return sb.ToString();
    }

    public static string TextOf(IntPtr h)
    {
        StringBuilder sb = new StringBuilder(256);
        GetWindowText(h, sb, sb.Capacity);
        return sb.ToString();
    }
}
'@

$tryPids = @()
$procs = Get-Process | Where-Object { $_.ProcessName -match 'python|Superstrike' }
foreach ($proc in $procs) { $tryPids += $proc.Id }

'Processes of interest:'
foreach ($proc in $procs) { '  pid={0,-6} {1}' -f $proc.Id, $proc.ProcessName }
''

'Visible top-level windows of those processes:'
foreach ($hwnd in [WinInspect]::Collect()) {

    $pidOfWindow = 0
    $null = [WinInspect]::GetWindowThreadProcessId($hwnd, [ref]$pidOfWindow)

    if ($tryPids -notcontains $pidOfWindow) { continue }
    if (-not [WinInspect]::IsWindowVisible($hwnd)) { continue }

    $ex = [int64][WinInspect]::GetWindowLongPtr($hwnd, -20)   # GWL_EXSTYLE
    $rect = New-Object WinInspect+RECT
    $null = [WinInspect]::GetWindowRect($hwnd, [ref]$rect)

    $flags = @()
    if ($ex -band 0x00000008) { $flags += 'TOPMOST' }
    if ($ex -band 0x00000020) { $flags += 'TRANSPARENT(click-through)' }
    if ($ex -band 0x00080000) { $flags += 'LAYERED' }
    if ($ex -band 0x08000000) { $flags += 'NOACTIVATE' }
    if ($ex -band 0x00000080) { $flags += 'TOOLWINDOW' }

    '  hwnd=0x{0:X}  class={1}  title="{2}"' -f [int64]$hwnd, [WinInspect]::ClassOf($hwnd), [WinInspect]::TextOf($hwnd)
    '    exstyle=0x{0:X8}  {1}' -f $ex, ($flags -join ' | ')
    '    rect=({0},{1})-({2},{3})  size={4}x{5}' -f $rect.Left, $rect.Top, $rect.Right, $rect.Bottom, ($rect.Right - $rect.Left), ($rect.Bottom - $rect.Top)
    ''
}

'WindowFromPoint probe (what the drag-and-drop loop would consider "under the cursor"):'
$point = New-Object WinInspect+POINT
$point.X = 960
$point.Y = 540
$hit = [WinInspect]::WindowFromPoint($point)
$hitPid = 0
$null = [WinInspect]::GetWindowThreadProcessId($hit, [ref]$hitPid)
'  screen point (960,540) -> hwnd=0x{0:X} class={1} pid={2}' -f [int64]$hit, [WinInspect]::ClassOf($hit), $hitPid
