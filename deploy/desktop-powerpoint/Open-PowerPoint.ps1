param(
    [Parameter(Mandatory = $true)][ValidateSet('open', 'focus')][string]$Action,
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
}
'@

function Get-PowerPoint {
    try { return [Runtime.InteropServices.Marshal]::GetActiveObject('PowerPoint.Application') }
    catch { return $null }
}

function Show-Presentation($Presentation, $Application) {
    $handle = [IntPtr]::Zero
    try { $handle = [IntPtr]$Presentation.SlideShowWindow.HWND } catch {}
    if ($handle -eq [IntPtr]::Zero) {
        if ($Presentation.Windows.Count -eq 0) { throw 'Presentation has no visible document window' }
        $window = $Presentation.Windows.Item(1)
        $window.Activate()
        $handle = [IntPtr]$Application.HWND
    }
    if ([WebGisPptWindow]::IsIconic($handle)) { [void][WebGisPptWindow]::ShowWindowAsync($handle, 9) }
    [void][WebGisPptWindow]::SetForegroundWindow($handle)
    return ([WebGisPptWindow]::GetForegroundWindow() -eq $handle)
}

try {
    $application = Get-PowerPoint
    if ($Action -eq 'open') {
        Add-Type -AssemblyName System.Windows.Forms
        $picker = New-Object System.Windows.Forms.OpenFileDialog
        $picker.Title = 'WebGIS：选择用 PowerPoint 打开的课件'
        $picker.Filter = 'PowerPoint 课件 (*.pptx;*.ppt)|*.pptx;*.ppt'
        $picker.CheckFileExists = $true
        $picker.Multiselect = $false
        try {
            if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
                @{status='cancelled'} | ConvertTo-Json -Compress
                exit 0
            }
            $SelectedPath = $picker.FileName
        } finally { $picker.Dispose() }
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
                    $protectedWindow.Activate()
                    $handle = [IntPtr]$application.HWND
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
        $handle = [IntPtr]$application.HWND
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
    @{status='failed';message='PowerPoint 未能打开或切换课件。请检查软件安装及 Office 提示框；不会自动保存、关闭文件或绕过安全提示。'} | ConvertTo-Json -Compress
    exit 0
}
