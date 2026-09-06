$ErrorActionPreference = 'Stop'

$packageRoot = Join-Path $PSScriptRoot '..\vendor\MachOMerger'
$checkout = Join-Path $packageRoot '.build\checkouts\SwiftMachO'
if (-not (Test-Path $checkout)) {
    throw "SwiftMachO checkout not found: $checkout"
}

# SwiftMachO's FAT.bestArch() references an Apple SDK constant which is not
# exposed by the Windows SDK. The wire value is part of the Mach-O format.
$fat = Join-Path $checkout 'Sources\SwiftMachO\MachO\FAT\FAT.swift'
$text = Get-Content $fat -Raw
if ($text -notmatch 'CPU_TYPE_X86_64') { throw 'Unexpected SwiftMachO FAT.swift: x86_64 constant not found' }
$text = $text.Replace('let targetCpuType = CPU_TYPE_X86_64', 'let targetCpuType: UInt32 = 0x01000007')
Set-Content -Path $fat -Value $text -NoNewline

# SharedCache is runtime-only Darwin functionality and is not used by the
# byte-level merger. Keep the API available but make construction fail on
# Windows instead of importing dlopen/dlsym symbols that do not exist there.
$cache = Join-Path $checkout 'Sources\SwiftMachO\dyld\SharedCache.swift'
$text = Get-Content $cache -Raw
if ($text -notmatch '#if canImport\(Darwin\)') {
    $text = $text.Replace('import Foundation', "import Foundation`r`n#if canImport(Darwin)`r`nimport Darwin`r`n#endif")
    $old = @"
    public init() throws {
        guard let funcPtr = dlsym(dlopen(nil, 0), "_dyld_get_shared_cache_range") else {
"@
    $new = @"
    public init() throws {
#if !canImport(Darwin)
        throw SharedCacheError.dyldFuncNotFound
#else
        guard let funcPtr = dlsym(dlopen(nil, 0), "_dyld_get_shared_cache_range") else {
"@
    $text = $text.Replace($old, $new)
    $text = $text.Replace("        cacheSize = shCacheSize`r`n    }", "        cacheSize = shCacheSize`r`n#endif`r`n    }")
    if ($text -notmatch '#if !canImport\(Darwin\)') { throw 'Failed to guard SwiftMachO SharedCache initializer' }
    Set-Content -Path $cache -Value $text -NoNewline
}

Write-Host "Patched SwiftMachO for Windows"
