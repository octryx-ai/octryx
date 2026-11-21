# octryx-claude installer for Windows (Octryx). The platform serves it with its URL filled in:
#   irm '<platform>/octryx-claude/install.ps1' | iex
#   & ([scriptblock]::Create((irm '<platform>/octryx-claude/install.ps1'))) [install|update|uninstall] [-NoLogin]
#       [-Workspace ID] [-Distribution NAME] [-Purge] [-NoPet]
#
# octryx-claude runs inside WSL2. Governed sessions require Claude Code's Bash sandbox
# (sandbox.failIfUnavailable): it exists on macOS, Linux and WSL2, not on native Windows, where
# Claude Code would exit at startup. So this script checks for a WSL2 distribution, runs the same
# install.sh inside it (package, shim, PATH, checksum check) and puts an octryx-claude.cmd into a
# per-user bin directory on the user PATH that forwards to WSL. No admin rights; nothing is written
# to ~/.claude (Windows or WSL) and Claude Code itself is never installed here.
#
# The Octryx pet (tray icon) needs native Windows: with a Python >= 3.11 on Windows (py launcher, python or uv),
# this script also builds %LOCALAPPDATA%\Octryx\octryx-claude\pet\venv with octryx-claude[pet] from the
# same verified wheel, writes pet\account.json (platform URL, WSL distribution and home; nothing secret: the pet
# borrows the gateway token from the WSL login through `octryx-claude api-key-helper`) and an octryx-pet.cmd shim.
# Without such a Python it says how to get one and goes on; -NoPet leaves the pet out. Never fatal.
# The pet is on by default: every install starts it and adds it to the logon (HKCU Run key) through
# `octryx-pet autostart`, unless the person turned it off (`octryx-pet disable` or "Turn off Octryx" in its menu;
# `octryx-pet enable` turns it on again).
# Windows PowerShell 5.1 and PowerShell 7 compatible.

$OctryxBaseUrl = '@@OCTRYX_BASE_URL@@'
$OctryxWorkspace = '@@OCTRYX_WORKSPACE@@'
# The operating system's own files (Thumbs.db, desktop.ini, ...; octryx_claude/os_junk.json): a created folder holding
# only those still counts as empty at uninstall.
$OctryxOsJunk = @('@@OCTRYX_OS_JUNK@@' -split ' ' | Where-Object { $_ })
$OctryxShimMark = 'rem octryx-claude shim (managed by the Octryx installer)'
$OctryxSafeValue = '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'
$OctryxSafeDistro = '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
$OctryxSafeHome = '^/[A-Za-z0-9._/-]{1,200}$'
$OctryxPetShimMark = 'rem octryx-pet shim (managed by the Octryx installer)'
# `octryx`: the short name for the same command; it calls octryx-claude.cmd next to it.
$OctryxAliasMark = 'rem octryx command (managed by the Octryx installer)'

function Get-OctryxBinDir {
    if (-not $env:LOCALAPPDATA) { throw 'octryx-claude installer: LOCALAPPDATA is not set' }
    return (Join-Path $env:LOCALAPPDATA 'Octryx\octryx-claude\bin')
}

# Directories this installer created under LOCALAPPDATA, one per line, so uninstall removes them once empty.
function Get-OctryxCreatedDirsFile { return (Join-Path $env:LOCALAPPDATA 'Octryx\octryx-claude\installer-created-dirs') }

# New-Item -Force $Path, recording the missing directories it creates (inside LOCALAPPDATA only).
function New-OctryxDirectory {
    param([string]$Path)
    $sep = [IO.Path]::DirectorySeparatorChar
    $root = $env:LOCALAPPDATA.TrimEnd('\', '/') + $sep
    $created = @()
    $dir = $Path
    while ($dir -and -not (Test-Path -LiteralPath $dir) -and $dir.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        $created += $dir
        $dir = Split-Path -Parent $dir
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    if ($created.Count -gt 0) { Add-Content -LiteralPath (Get-OctryxCreatedDirsFile) -Value $created -Encoding ASCII }
}

# True when the items are all the operating system's own files (no folder, nothing else).
function Test-OctryxOnlyOsJunk($items) {
    foreach ($item in $items) {
        if ($item.PSIsContainer) { return $false }
        $name = $item.Name
        if (-not @($OctryxOsJunk | Where-Object { $name -like $_ }).Count) { return $false }
    }
    return $true
}

# Removes the recorded directories that are empty, deepest first; never one with content. A folder holding only the
# operating system's own files counts as empty.
function Remove-OctryxCreatedDirs {
    $record = Get-OctryxCreatedDirsFile
    if (-not (Test-Path -LiteralPath $record)) { return }
    $dirs = @(Get-Content -LiteralPath $record | Where-Object { $_ } | Select-Object -Unique | Sort-Object -Property Length -Descending)
    Remove-Item -Force -LiteralPath $record
    $kept = @()
    foreach ($dir in $dirs) {
        if (-not (Test-Path -LiteralPath $dir -PathType Container)) { continue }
        $items = @(Get-ChildItem -Force -LiteralPath $dir)
        if (Test-OctryxOnlyOsJunk $items) {
            foreach ($item in $items) { Remove-Item -Force -LiteralPath $item.FullName }
            Remove-Item -LiteralPath $dir
        } else { $kept += $dir }
    }
    if ($kept.Count -gt 0 -and (Test-Path -LiteralPath (Split-Path -Parent $record))) {
        Set-Content -LiteralPath $record -Value $kept -Encoding ASCII
    }
}

# The user PATH with $Entry added (or removed), compared case-insensitively, empty parts dropped.
function Get-OctryxPathValue {
    param([string]$Current, [string]$Entry, [switch]$Remove)
    $parts = @()
    foreach ($part in ($Current -split ';')) {
        if ($part -and ($part.TrimEnd('\') -ne $Entry.TrimEnd('\'))) { $parts += $part }
    }
    if (-not $Remove) { $parts += $Entry }
    return ($parts -join ';')
}

function Set-OctryxUserPath {
    param([string]$Entry, [switch]$Remove)
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($null -eq $current) { $current = '' }
    $next = Get-OctryxPathValue -Current $current -Entry $Entry -Remove:$Remove
    if ($next -ne $current) { [Environment]::SetEnvironmentVariable('Path', $next, 'User') }
    $env:Path = Get-OctryxPathValue -Current $env:Path -Entry $Entry -Remove:$Remove
}

function Get-OctryxShimContent {
    param([string]$Distribution, [string]$WslHome)
    if ($Distribution -notmatch $OctryxSafeDistro) { throw "octryx-claude installer: unusable WSL distribution name: $Distribution" }
    if ($WslHome -notmatch $OctryxSafeHome) { throw "octryx-claude installer: unusable WSL home directory: $WslHome" }
    return @(
        '@echo off',
        $OctryxShimMark,
        "wsl.exe -d $Distribution -e $WslHome/.local/bin/octryx-claude %*",
        'exit /b %ERRORLEVEL%'
    ) -join "`r`n"
}

function Get-OctryxAliasContent {
    return @(
        '@echo off',
        $OctryxAliasMark,
        'call "%~dp0octryx-claude.cmd" %*',
        'exit /b %ERRORLEVEL%'
    ) -join "`r`n"
}

function Set-OctryxAlias {
    param([string]$BinDir)
    $alias = Join-Path $BinDir 'octryx.cmd'
    if ((Test-Path $alias) -and ((Get-Content -Raw $alias) -notmatch [regex]::Escape($OctryxAliasMark))) {
        Write-Host "octryx-claude: kept $alias (not written by this installer); use octryx-claude."
        return
    }
    Set-Content -Path $alias -Value (Get-OctryxAliasContent) -Encoding ASCII
}

function Remove-OctryxAlias {
    param([string]$BinDir)
    $alias = Join-Path $BinDir 'octryx.cmd'
    if ((Test-Path $alias) -and ((Get-Content -Raw $alias) -match [regex]::Escape($OctryxAliasMark))) { Remove-Item -Force $alias }
}

function Get-OctryxWsl {
    $wsl = Get-Command 'wsl.exe' -ErrorAction SilentlyContinue
    if (-not $wsl) {
        throw ("octryx-claude needs WSL2 (Claude Code's sandbox does not run on native Windows). Install it once " +
            "in an administrator PowerShell: wsl --install   then restart Windows and rerun this installer.")
    }
    return $wsl.Source
}

# Distribution name, home directory and kernel of the (default or named) WSL distribution.
function Get-OctryxWslProbe {
    param([string]$Wsl, [string]$Distribution)
    $selector = @()
    if ($Distribution) { $selector = @('-d', $Distribution) }
    $lines = & $Wsl @selector -e sh -c 'printf %s\\n $WSL_DISTRO_NAME $HOME; uname -r'
    if ($LASTEXITCODE -ne 0 -or @($lines).Count -lt 3) {
        throw ("octryx-claude installer: no usable WSL distribution. Install one once with: wsl --install -d Ubuntu " +
            "(administrator PowerShell), open it to create your user, then rerun this installer.")
    }
    $lines = @($lines)
    $probe = [pscustomobject]@{ Distribution = "$($lines[0])".Trim(); Home = "$($lines[1])".Trim(); Kernel = "$($lines[2])".Trim() }
    if ($probe.Kernel -notmatch 'microsoft-standard|WSL2') {
        throw ("octryx-claude installer: $($probe.Distribution) runs on WSL1; the sandbox needs WSL2: " +
            "wsl --set-version $($probe.Distribution) 2")
    }
    return $probe
}

# --- the Octryx pet (native Windows) ----------------------------------------------------------------------------
function Get-OctryxPetDir { return (Join-Path $env:LOCALAPPDATA 'Octryx\octryx-claude\pet') }

# A Python >= 3.11 on Windows for the pet: the py launcher, then python.exe (not the Microsoft Store stub under
# WindowsApps, which only opens the Store), then uv. Returns the command as an array, or $null.
function Find-OctryxPetPython {
    $probe = 'import sys; print(sys.version_info >= (3, 11))'
    $py = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($py) {
        $out = & $py.Source -3 -c $probe 2>$null
        if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True') { return @($py.Source, '-3') }
    }
    $python = Get-Command 'python.exe' -ErrorAction SilentlyContinue
    if ($python -and ($python.Source -notmatch '[\\/]WindowsApps[\\/]')) {
        $out = & $python.Source -c $probe 2>$null
        if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True') { return @($python.Source) }
    }
    $uv = Get-Command 'uv.exe' -ErrorAction SilentlyContinue
    if ($uv) { return @($uv.Source, 'uv') }
    return $null
}

function Get-OctryxPetShimContent {
    param([string]$Python)
    if ($Python -match '["%&|<>^]') { throw "octryx-claude installer: unusable pet Python path: $Python" }
    return @(
        '@echo off',
        $OctryxPetShimMark,
        "`"$Python`" -m octryx_claude.pet %*",
        'exit /b %ERRORLEVEL%'
    ) -join "`r`n"
}

function Get-OctryxPetAccountJson {
    param([string]$BaseUrl, [string]$Distribution, [string]$WslHome)
    if ($Distribution -notmatch $OctryxSafeDistro) { throw "octryx-claude installer: unusable WSL distribution name: $Distribution" }
    if ($WslHome -notmatch $OctryxSafeHome) { throw "octryx-claude installer: unusable WSL home directory: $WslHome" }
    return ([ordered]@{ base_url = $BaseUrl; wsl_distribution = $Distribution; wsl_home = $WslHome } | ConvertTo-Json)
}

# Running pets of this venv hold its files open; they are stopped before the venv is replaced or removed.
function Stop-OctryxPet {
    param([string]$VenvDir)
    if (-not (Get-Command 'Get-CimInstance' -ErrorAction SilentlyContinue)) { return }
    $prefix = $VenvDir.TrimEnd('\') + '\'
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Remove-OctryxPetAutostart {
    Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'OctryxPet' -ErrorAction SilentlyContinue
}

function Install-OctryxPet {
    param([string]$BinDir, [string]$Distribution, [string]$WslHome)
    $petDir = Get-OctryxPetDir
    $venv = Join-Path $petDir 'venv'
    $python = Find-OctryxPetPython
    if (-not $python) {
        Write-Host ('octryx-claude: the Octryx pet (tray icon) needs Python 3.11 or newer on Windows: ' +
            'winget install Python.Python.3.12   then rerun this installer. octryx-claude works without it.')
        return
    }
    $meta = Invoke-RestMethod -Uri "$OctryxBaseUrl/octryx-claude/version" -TimeoutSec 30
    $version = "$($meta.version)"; $filename = "$($meta.filename)"; $sha = "$($meta.sha256)"
    if ($version -notmatch '^[0-9][0-9A-Za-z.+_-]{0,63}$' -or
        $filename -notmatch '^octryx_claude-[0-9A-Za-z.+_-]+-py3-none-any\.whl$' -or $sha -notmatch '^[0-9a-f]{64}$') {
        throw 'the platform answered no usable package version'
    }
    $versionFile = Join-Path $petDir 'installed-version'
    $pythonw = Join-Path $venv 'Scripts\pythonw.exe'
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    $current = ''
    if (Test-Path -LiteralPath $versionFile) { $current = (Get-Content -Raw -LiteralPath $versionFile).Trim() }
    if ($current -ne $version -or -not (Test-Path -LiteralPath $pythonw)) {
        $tmp = Join-Path ([IO.Path]::GetTempPath()) ("octryx-pet-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $tmp | Out-Null
        try {
            $wheel = Join-Path $tmp $filename
            Invoke-WebRequest -Uri "$OctryxBaseUrl/octryx-claude/package/$version" -OutFile $wheel -UseBasicParsing -TimeoutSec 300
            $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $wheel).Hash.ToLowerInvariant()
            if ($actual -ne $sha) { throw "checksum mismatch for $filename; the pet was not installed" }
            New-OctryxDirectory -Path $petDir
            Stop-OctryxPet -VenvDir $venv
            if (Test-Path -LiteralPath $venv) { Remove-Item -Recurse -Force -LiteralPath $venv }
            $requirement = 'octryx-claude[pet] @ ' + ([Uri]$wheel).AbsoluteUri
            if ($python[-1] -eq 'uv') {
                & $python[0] venv --quiet --no-cache --python '>=3.11' $venv
                if ($LASTEXITCODE -eq 0) { & $python[0] pip install --quiet --no-cache --python $venvPython $requirement }
            } else {
                $launcher = $python[0]; $launcherArgs = @($python | Select-Object -Skip 1)
                & $launcher @launcherArgs -m venv $venv
                if ($LASTEXITCODE -eq 0) { & $venvPython -m pip install --quiet --disable-pip-version-check --no-cache-dir $requirement }
            }
            & $venvPython -c 'import octryx_claude.pet.tray' 2>$null
            if ($LASTEXITCODE -ne 0) {
                if (Test-Path -LiteralPath $venv) { Remove-Item -Recurse -Force -LiteralPath $venv }
                throw 'pip/uv could not install octryx-claude[pet] (see the messages above)'
            }
            Set-Content -LiteralPath $versionFile -Value $version -Encoding ASCII
        } finally {
            Remove-Item -Recurse -Force -LiteralPath $tmp -ErrorAction SilentlyContinue
        }
    }
    Set-Content -LiteralPath (Join-Path $petDir 'account.json') -Encoding ASCII `
        -Value (Get-OctryxPetAccountJson -BaseUrl $OctryxBaseUrl -Distribution $Distribution -WslHome $WslHome)
    $petShim = Join-Path $BinDir 'octryx-pet.cmd'
    if ((Test-Path $petShim) -and ((Get-Content -Raw $petShim) -notmatch [regex]::Escape($OctryxPetShimMark))) {
        throw "$petShim exists and was not written by this installer"
    }
    Set-Content -Path $petShim -Value (Get-OctryxPetShimContent -Python (Join-Path $venv 'Scripts\python.exe')) -Encoding ASCII
    Write-Host "octryx-claude: Octryx pet $version installed."
    # On by default: the Run key and a start now, unless the person turned it off. A running pet
    # of an unchanged venv stays; the new start then exits at once (one pet per user).
    & $venvPython -m octryx_claude.pet autostart --restart
    if ($LASTEXITCODE -ne 0) { Write-Host 'octryx-claude: the Octryx pet could not be started now (try: octryx-pet enable).' }
}

function Uninstall-OctryxPet {
    param([string]$BinDir, [switch]$Purge)
    $petDir = Get-OctryxPetDir
    $venv = Join-Path $petDir 'venv'
    Remove-OctryxPetAutostart  # not `pet disable`: that would also record "turned off" for a later install
    Stop-OctryxPet -VenvDir $venv
    foreach ($item in @($venv, (Join-Path $petDir 'installed-version'), (Join-Path $petDir 'account.json'))) {
        if (Test-Path -LiteralPath $item) { Remove-Item -Recurse -Force -LiteralPath $item }
    }
    if ($Purge -and (Test-Path -LiteralPath $petDir)) { Remove-Item -Recurse -Force -LiteralPath $petDir }
    $petShim = Join-Path $BinDir 'octryx-pet.cmd'
    if ((Test-Path $petShim) -and ((Get-Content -Raw $petShim) -match [regex]::Escape($OctryxPetShimMark))) { Remove-Item -Force $petShim }
}

function Invoke-OctryxClaudeInstaller {
    param(
        [Parameter(Position = 0)][ValidateSet('install', 'update', 'uninstall')][string]$Command = 'install',
        [switch]$NoLogin,
        [switch]$Purge,
        [string]$Workspace = '',
        [string]$Distribution = '',
        [switch]$NoPet
    )
    $ErrorActionPreference = 'Stop'
    if ($OctryxBaseUrl -like '*@@*') { throw 'octryx-claude installer: unfilled template; download it from your platform' }
    if (-not $Workspace) { $Workspace = $OctryxWorkspace }
    if ($Workspace -and ($Workspace -notmatch $OctryxSafeValue)) { throw "octryx-claude installer: unusable Workspace: $Workspace" }
    if ($Distribution -and ($Distribution -notmatch $OctryxSafeDistro)) { throw "octryx-claude installer: unusable distribution: $Distribution" }

    $wsl = Get-OctryxWsl
    $probe = Get-OctryxWslProbe -Wsl $wsl -Distribution $Distribution
    $binDir = Get-OctryxBinDir
    $shim = Join-Path $binDir 'octryx-claude.cmd'
    $linuxShim = "$($probe.Home)/.local/bin/octryx-claude"
    Write-Host "octryx-claude: WSL2 distribution $($probe.Distribution)"

    if ($Command -eq 'uninstall') {
        $flags = 'uninstall'
        if ($Purge) { $flags = 'uninstall --purge' }
        & $wsl -d $probe.Distribution -e bash -c "set -o pipefail; if [ -f ~/.octryx/claude/installer/install.sh ]; then bash ~/.octryx/claude/installer/install.sh $flags; else curl -fsSL '$OctryxBaseUrl/octryx-claude/install.sh' | bash -s -- $flags; fi"
        if ($LASTEXITCODE -ne 0) { throw 'octryx-claude installer: uninstall inside WSL failed' }
        if ((Test-Path $shim) -and ((Get-Content -Raw $shim) -match [regex]::Escape($OctryxShimMark))) { Remove-Item -Force $shim }
        Remove-OctryxAlias -BinDir $binDir
        Uninstall-OctryxPet -BinDir $binDir -Purge:$Purge
        Set-OctryxUserPath -Entry $binDir -Remove
        Remove-OctryxCreatedDirs
        Write-Host 'octryx-claude: removed the Windows shim and its PATH entry.'
        return
    }

    $script = "$OctryxBaseUrl/octryx-claude/install.sh"
    $flags = "$Command --no-login"
    # install.sh stores the platform URL and this Workspace (validated above) also when no login follows.
    if ($Command -eq 'install' -and $Workspace) { $flags += " --workspace $Workspace" }
    # pipefail: a failed download must fail the install, not run an empty script that exits 0.
    & $wsl -d $probe.Distribution -e bash -c "set -o pipefail; curl -fsSL '$script' | bash -s -- $flags"
    if ($LASTEXITCODE -ne 0) { throw 'octryx-claude installer: the install inside WSL failed (see the messages above)' }
    & $wsl -d $probe.Distribution -e test -x $linuxShim
    if ($LASTEXITCODE -ne 0) { throw "octryx-claude installer: the install inside WSL left no $linuxShim; nothing was set up on Windows" }

    New-OctryxDirectory -Path $binDir
    if ((Test-Path $shim) -and ((Get-Content -Raw $shim) -notmatch [regex]::Escape($OctryxShimMark))) {
        throw "octryx-claude installer: $shim exists and was not written by this installer; move it away and rerun"
    }
    Set-Content -Path $shim -Value (Get-OctryxShimContent -Distribution $probe.Distribution -WslHome $probe.Home) -Encoding ASCII
    Set-OctryxAlias -BinDir $binDir
    Set-OctryxUserPath -Entry $binDir
    Write-Host "octryx-claude: $shim forwards to $linuxShim in $($probe.Distribution) (short: octryx)."

    if ($Command -eq 'install' -and -not $NoLogin) {
        $login = @('login', '--base-url', $OctryxBaseUrl)
        if ($Workspace) { $login += @('--workspace', $Workspace) }
        & $wsl -d $probe.Distribution -e $linuxShim @login
        if ($LASTEXITCODE -ne 0) { throw "octryx-claude installer: installed, but the login did not complete; run: octryx-claude login --base-url $OctryxBaseUrl" }
    }
    & $wsl -d $probe.Distribution -e $linuxShim status
    if (-not $NoPet) {
        try { Install-OctryxPet -BinDir $binDir -Distribution $probe.Distribution -WslHome $probe.Home }
        catch { Write-Host "octryx-claude: the Octryx pet was not installed ($($_.Exception.Message)); octryx-claude works without it." }
    }
    Write-Host 'octryx-claude: ready. Open a new terminal and run: octryx-claude'
}

if ($env:OCTRYX_INSTALLER_NO_RUN -ne '1') { Invoke-OctryxClaudeInstaller @args }
