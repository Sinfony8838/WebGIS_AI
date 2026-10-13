param(
    [Parameter(Mandatory = $true)][ValidateSet('open', 'focus', 'launch')][string]$Action,
    [string]$SelectedPath = ''
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

# Window activation only: no keystroke injection, persistent security changes,
# Save/Close/Quit calls or process-tree termination.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class WebGisPptWindow {
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int command);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindow callback, IntPtr parameter);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr window, System.Text.StringBuilder text, int length);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr window, System.Text.StringBuilder text, int length);
    private delegate bool EnumWindow(IntPtr window, IntPtr parameter);
    // PowerPoint's Application/DocumentWindow COM objects do not expose HWND
    // on all Office versions. Resolve only a unique matching PowerPoint frame
    // in this user session; ambiguous document names fail without switching.
    public static IntPtr FindFrame(string caption, string name) { return FindMatching(caption, name, false); }
    public static IntPtr FindSlideShow(string name) { return FindMatching("", name, true); }
    public static IntPtr[] ExistingWindows() {
        var matches = new System.Collections.Generic.List<IntPtr>();
        int session = System.Diagnostics.Process.GetCurrentProcess().SessionId;
        EnumWindows(delegate(IntPtr window, IntPtr parameter) {
            if (!IsWindowVisible(window)) return true;
            var kind = new System.Text.StringBuilder(128);
            GetClassName(window, kind, kind.Capacity);
            if (kind.ToString() != "PPTFrameClass" && kind.ToString() != "screenClass") return true;
            uint pid; GetWindowThreadProcessId(window, out pid);
            try {
                var process = System.Diagnostics.Process.GetProcessById((int)pid);
                if (process.SessionId == session && string.Equals(process.ProcessName, "POWERPNT", StringComparison.OrdinalIgnoreCase))
                    matches.Add(window);
            } catch { }
            return true;
        }, IntPtr.Zero);
        return matches.ToArray();
    }
    public static bool HasPowerPointProcess() {
        int session = System.Diagnostics.Process.GetCurrentProcess().SessionId;
        foreach (var process in System.Diagnostics.Process.GetProcessesByName("POWERPNT")) {
            try { if (process.SessionId == session) return true; } catch { }
            finally { process.Dispose(); }
        }
        return false;
    }
    private static IntPtr FindMatching(string caption, string name, bool slideShow) {
        var matches = new System.Collections.Generic.List<IntPtr>();
        int session = System.Diagnostics.Process.GetCurrentProcess().SessionId;
        EnumWindows(delegate(IntPtr window, IntPtr parameter) {
            if (!IsWindowVisible(window)) return true;
            var kind = new System.Text.StringBuilder(128);
            GetClassName(window, kind, kind.Capacity);
            if (slideShow ? kind.ToString() == "PPTFrameClass" : kind.ToString() != "PPTFrameClass") return true;
            uint pid; GetWindowThreadProcessId(window, out pid);
            try {
                var process = System.Diagnostics.Process.GetProcessById((int)pid);
                if (process.SessionId != session || !string.Equals(process.ProcessName, "POWERPNT", StringComparison.OrdinalIgnoreCase)) return true;
            } catch { return true; }
            var text = new System.Text.StringBuilder(1024);
            GetWindowText(window, text, text.Capacity);
            string title = text.ToString();
            bool match = !string.IsNullOrEmpty(caption) && (title == caption || title == caption + " - PowerPoint");
            match |= !string.IsNullOrEmpty(name) && (title == name || title == name + " - PowerPoint");
            if (slideShow) match = !string.IsNullOrEmpty(name) && title.TrimEnd().EndsWith(name, StringComparison.OrdinalIgnoreCase);
            if (match) matches.Add(window);
            return true;
        }, IntPtr.Zero);
        return matches.Count == 1 ? matches[0] : IntPtr.Zero;
    }
}
'@

function Get-PowerPoint {
    try {
        $active = [Runtime.InteropServices.Marshal]::GetActiveObject('PowerPoint.Application')
        # Some presentation suites publish the Microsoft ProgID in the running
        # object table. Never enumerate or activate a different office suite.
        if (Test-Path -LiteralPath (Join-Path ([string]$active.Path) 'POWERPNT.EXE') -PathType Leaf) { return $active }
        return $null
    }
    catch { return $null }
}

function Start-PowerPointApplication {
    $keys = @('Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE',
              'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE')
    foreach ($key in $keys) {
        if (-not (Test-Path -LiteralPath $key)) { continue }
        $executable = [string](Get-Item -LiteralPath $key).GetValue('')
        if ([IO.Path]::GetFileName($executable) -ine 'POWERPNT.EXE' -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) { continue }
        # Normal interactive launch keeps the window alive after the worker
        # exits; an automation-only COM startup can disappear on release.
        Start-Process -FilePath $executable | Out-Null
        return
    }
    throw 'Installed PowerPoint executable was not found'
}

function Show-Presentation($Presentation, $Application) {
    $handle = [IntPtr]::Zero
    # Resolve the running show by its presentation, not the editor's HWND.
    # Office versions that omit HWND still expose the SlideShowWindows collection.
    $shows = @($Application.SlideShowWindows | Where-Object {
        [string]::Equals($_.Presentation.FullName, $Presentation.FullName, [StringComparison]::OrdinalIgnoreCase)
    })
    if ($shows.Count -gt 1) { throw 'Presentation has ambiguous slide show windows' }
    if ($shows.Count -eq 1) {
        $handle = [WebGisPptWindow]::FindSlideShow([string]$Presentation.Name)
        if ($handle -eq [IntPtr]::Zero) { throw 'PowerPoint slide show window is unavailable or ambiguous' }
        $shows[0].Activate()
    } else {
        if ($Presentation.Windows.Count -eq 0) { throw 'Presentation has no visible document window' }
        $window = $Presentation.Windows.Item(1)
        $handle = [WebGisPptWindow]::FindFrame([string]$window.Caption, [string]$Presentation.Name)
        if ($handle -eq [IntPtr]::Zero) { throw 'PowerPoint document window is unavailable or ambiguous' }
        $window.Activate()
    }
    if ([WebGisPptWindow]::IsIconic($handle)) { [void][WebGisPptWindow]::ShowWindowAsync($handle, 9) }
    [void][WebGisPptWindow]::SetForegroundWindow($handle)
    return ([WebGisPptWindow]::GetForegroundWindow() -eq $handle)
}

try {
    # Native-window reuse comes BEFORE COM lookup. ROT can be unavailable even
    # while an existing deck is open. Never open another instance in that case.
    if ($Action -eq 'launch') {
        $windows = @([WebGisPptWindow]::ExistingWindows())
        if ($windows.Count -eq 0) {
            if ([WebGisPptWindow]::HasPowerPointProcess()) { throw 'PowerPoint has no usable main window; check Office prompts' }
            Start-PowerPointApplication
            for ($attempt = 0; $attempt -lt 40; $attempt++) {
                $windows = @([WebGisPptWindow]::ExistingWindows())
                if ($windows.Count -gt 0) { break }
                Start-Sleep -Milliseconds 250
            }
        }
        # The palette, not this worker, lets the teacher choose among windows.
        if ($windows.Count -eq 0) { throw 'PowerPoint launch did not expose a usable window' }
        @{status='focused';file_name='PowerPoint';foreground=$false} | ConvertTo-Json -Compress
        exit 0
    }
    $application = Get-PowerPoint
    # The palette starts/focuses the application without a file-selection step.
    # The teacher opens their deck normally inside PowerPoint if none is open.
    if ($Action -eq 'open') {
        # Office owns the visible picker. A hidden console host must not own
        # the dialog; never use Execute(), which could bypass validation.
        if (-not $application) { $application = New-Object -ComObject PowerPoint.Application }
        $application.Visible = -1
        $picker = $application.FileDialog(3) # msoFileDialogFilePicker
        $picker.Title = 'WebGIS：选择用 PowerPoint 打开的课件'
        $picker.AllowMultiSelect = $false
        $picker.Filters.Clear()
        [void]$picker.Filters.Add('PowerPoint 课件', '*.pptx;*.ppt')
        $picker.InitialFileName = [Environment]::GetFolderPath('UserProfile') + '\'
        if ($picker.Show() -ne -1) {
            @{status='cancelled'} | ConvertTo-Json -Compress
            exit 0
        }
        $SelectedPath = [string]$picker.SelectedItems.Item(1)
    }
    if ($SelectedPath -and $Action -eq 'open') {
        $resolved = Get-Item -LiteralPath $SelectedPath
        if ($resolved.PSIsContainer -or $resolved.Extension.ToLowerInvariant() -notin @('.pptx', '.ppt')) {
            throw 'Select a PowerPoint presentation'
        }
        $SelectedPath = $resolved.FullName
    }
    $presentation = $null
    if ($application -and $SelectedPath) {
        foreach ($candidate in $application.Presentations) {
            if ([string]::Equals($candidate.FullName, $SelectedPath, [StringComparison]::OrdinalIgnoreCase)) {
                $presentation = $candidate; break
            }
        }
        # Never call Edit() or dismiss Protected View/security prompts.
        if (-not $presentation) {
            foreach ($protectedWindow in $application.ProtectedViewWindows) {
                $candidate = $protectedWindow.Presentation
                if ([string]::Equals($candidate.FullName, $SelectedPath, [StringComparison]::OrdinalIgnoreCase)) {
                    $handle = [WebGisPptWindow]::FindFrame([string]$protectedWindow.Caption, [string]$candidate.Name)
                    if ($handle -eq [IntPtr]::Zero) { throw 'Protected View window is unavailable or ambiguous' }
                    $protectedWindow.Activate()
                    if ([WebGisPptWindow]::IsIconic($handle)) { [void][WebGisPptWindow]::ShowWindowAsync($handle, 9) }
                    [void][WebGisPptWindow]::SetForegroundWindow($handle)
                    @{status='focused';file_name=$candidate.Name;selected_path=$SelectedPath;foreground=([WebGisPptWindow]::GetForegroundWindow() -eq $handle)} | ConvertTo-Json -Compress
                    exit 0
                }
            }
        }
    }
    if (-not $SelectedPath -and $application -and $application.Presentations.Count -gt 0) {
        $presentation = $application.ActivePresentation
        $SelectedPath = $presentation.FullName
        # An unsaved presentation has a title rather than a reusable path.
        if (-not [IO.Path]::IsPathRooted($SelectedPath)) { $SelectedPath = '' }
    }
    if (-not $SelectedPath -and -not $presentation -and $application) {
        # Also focus an existing start screen or Protected View window;
        # selecting/activating it must never implicitly enable editing.
        $handle = [WebGisPptWindow]::FindFrame('PowerPoint', '')
        if ($handle -eq [IntPtr]::Zero) { throw 'PowerPoint start window is unavailable or ambiguous' }
        if ([WebGisPptWindow]::IsIconic($handle)) { [void][WebGisPptWindow]::ShowWindowAsync($handle, 9) }
        [void][WebGisPptWindow]::SetForegroundWindow($handle)
        @{status='focused';file_name='PowerPoint';foreground=([WebGisPptWindow]::GetForegroundWindow() -eq $handle)} | ConvertTo-Json -Compress
        exit 0
    }
    if (-not $presentation -and -not $SelectedPath) {
        @{status='failed';message='当前没有打开的 PowerPoint 课件，请先点击“打开 PPT”选择文件。'} | ConvertTo-Json -Compress
        exit 0
    }
    $status = 'focused'
    if (-not $presentation) {
        # Check disk only when opening, so an already open/unsaved document
        # remains focusable without inventing or requiring a disk file.
        $resolved = Get-Item -LiteralPath $SelectedPath
        if ($resolved.PSIsContainer -or $resolved.Extension.ToLowerInvariant() -notin @('.pptx', '.ppt')) {
            throw 'Select a PowerPoint presentation'
        }
        $SelectedPath = $resolved.FullName
        if (-not $application) { $application = New-Object -ComObject PowerPoint.Application }
        $application.Visible = -1
        # COM defaults to enabling macros. Use the teacher's Trust Center
        # policy for this open, retaining ForceDisable if already selected.
        # Restore the previous automation mode; never change Trust Center.
        $previousSecurity = [int]$application.AutomationSecurity
        try {
            $application.AutomationSecurity = [Math]::Max(2, $previousSecurity)
            $presentation = $application.Presentations.Open($SelectedPath, 0, 0, -1)
        } finally { $application.AutomationSecurity = $previousSecurity }
        $status = 'opened'
    }
    $foreground = Show-Presentation $presentation $application
    @{status=$status;file_name=$presentation.Name;selected_path=$SelectedPath;foreground=$foreground} | ConvertTo-Json -Compress
} catch {
    # Diagnostic metadata only; never emit local paths, captions or raw Office errors.
    [Console]::Error.WriteLine(('PowerPoint failure {0} HResult {1:X8} at line {2}' -f $_.Exception.GetType().FullName, $_.Exception.HResult, $_.InvocationInfo.ScriptLineNumber))
    @{status='failed';message='PowerPoint 未能打开或切换课件。请检查软件安装及 Office 提示框；不会自动保存、关闭文件或绕过安全提示。'} | ConvertTo-Json -Compress
    exit 0
}
