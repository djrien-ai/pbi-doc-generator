param(
    [Parameter(Mandatory = $true)]
    [string]$ZipPath
)

$ErrorActionPreference = "Stop"
Write-Host "=== E2E Verification of Portable Windows ZIP ==="
Write-Host "ZIP file: $ZipPath ($(([math]::Round((Get-Item $ZipPath).Length / 1MB, 2))) MB)"

$workRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pbidoc_user_pc_sim_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$extractDir = Join-Path $workRoot "ExtractedApp"
$catalogDir = Join-Path $workRoot "UserCatalog"
$sampleRoot = Join-Path $workRoot "SampleModel"
New-Item -ItemType Directory -Force -Path $extractDir, $catalogDir, $sampleRoot | Out-Null

Expand-Archive -Path $ZipPath -DestinationPath $extractDir -Force

$exePath = Join-Path $extractDir "PBI_Doc_Generator.exe"
$internalDir = Join-Path $extractDir "_internal"
$startHere = Join-Path $extractDir "START_HERE.txt"

if (-not (Test-Path $exePath)) { throw "Missing PBI_Doc_Generator.exe in extracted ZIP!" }
if (-not (Test-Path $internalDir)) { throw "Missing _internal folder in extracted ZIP!" }
if (-not (Test-Path $startHere)) { throw "Missing START_HERE.txt in extracted ZIP!" }
Write-Host "[PASS] ZIP structure verified (PBI_Doc_Generator.exe + _internal + START_HERE.txt)"

# Simulate a clean end-user Windows PC with NO Python or developer tools on PATH
$origPath = $env:PATH
$origPyHome = $env:PYTHONHOME
$origPyPath = $env:PYTHONPATH
$proc = $null

try {
    $env:PATH = "C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0"
    $env:PYTHONHOME = $null
    $env:PYTHONPATH = $null
    Push-Location $extractDir

    # 1. Version check
    $verOut = & $exePath --version 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or $verOut -notmatch "1\.0\.0") {
        throw "Version check failed (exit $LASTEXITCODE): $verOut"
    }
    Write-Host "[PASS] Clean-PATH --version check: $($verOut.Trim())"

    # 2. Launch Studio server in background (same entry point as double-click, minus browser tab)
    $port = 18765
    $stdoutLog = Join-Path $workRoot "studio_stdout.log"
    $stderrLog = Join-Path $workRoot "studio_stderr.log"
    $proc = Start-Process -FilePath $exePath `
        -ArgumentList @("studio", "--no-browser", "--port", "$port", "--catalog", $catalogDir) `
        -WorkingDirectory $extractDir `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $baseUrl = "http://127.0.0.1:$port"
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) {
            $errTxt = if (Test-Path $stderrLog) { Get-Content -Raw $stderrLog } else { "" }
            throw "PBI_Doc_Generator.exe exited prematurely (code $($proc.ExitCode)): $errTxt"
        }
        try {
            $resp = Invoke-WebRequest -Uri "$baseUrl/api/status" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {}
    }
    if (-not $ready) {
        $errTxt = if (Test-Path $stderrLog) { Get-Content -Raw $stderrLog } else { "" }
        throw "Studio server did not become ready on $baseUrl within 15s. Stderr: $errTxt"
    }
    Write-Host "[PASS] Studio server started cleanly on $baseUrl without Python on PATH"

    # 3. Verify Studio UI HTML
    $uiResp = Invoke-WebRequest -Uri "$baseUrl/" -UseBasicParsing -TimeoutSec 5
    if ($uiResp.Content -notmatch "Sign in with Microsoft" -or $uiResp.Content -notmatch "Select Project Folder") {
        throw "Studio home page missing expected UI controls!"
    }
    Write-Host "[PASS] Studio Web UI HTML rendered (200 OK)"

    # 4. Simulate browser folder upload (/api/upload-local-folder) with Star-Schema TMDL + DAX + Power Query M
    $modelTmdl = "model Model`n`tculture: en-US`n"
    $relTmdl = "relationship rel1`n`tfromColumn: 'Fact Sales'.CustomerKey`n`ttoColumn: 'Dim Customer'.CustomerKey`n"
    $factTmdl = @"
table 'Fact Sales'
	measure 'Total Revenue' = SUM('Fact Sales'[NetAmount])
		displayFolder: Financials
	measure 'Avg Revenue per Customer' = DIVIDE([Total Revenue], DISTINCTCOUNT('Dim Customer'[CustomerKey]), 0)
		displayFolder: Financials
	column CustomerKey
		dataType: int64
		sourceColumn: CustomerKey
	column NetAmount
		dataType: double
		sourceColumn: NetAmount
	partition 'Fact Sales' = m
		mode: import
		source =
			let
				Source = Sql.Database("sql-prod.contoso.local", "EDW"),
				Sales = Source{[Schema="dbo",Item="FACT_SALES"]}[Data]
			in
				Sales
"@
    $dimTmdl = @"
table 'Dim Customer'
	column CustomerKey
		dataType: int64
		sourceColumn: CustomerKey
	column CustomerName
		dataType: string
		sourceColumn: CustomerName
	partition 'Dim Customer' = m
		mode: import
		source =
			let
				Source = Sql.Database("sql-prod.contoso.local", "EDW"),
				Cust = Source{[Schema="dbo",Item="DIM_CUSTOMER"]}[Data]
			in
				Cust
"@

    $uploadPayload = @{
        files = @(
            @{ path = "RetailProject/RetailAnalytics.SemanticModel/definition/model.tmdl"; content = $modelTmdl },
            @{ path = "RetailProject/RetailAnalytics.SemanticModel/definition/relationships.tmdl"; content = $relTmdl },
            @{ path = "RetailProject/RetailAnalytics.SemanticModel/definition/tables/FactSales.tmdl"; content = $factTmdl },
            @{ path = "RetailProject/RetailAnalytics.SemanticModel/definition/tables/DimCustomer.tmdl"; content = $dimTmdl }
        )
    } | ConvertTo-Json -Depth 6

    $impResp = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/upload-local-folder" -Body $uploadPayload -ContentType "application/json; charset=utf-8" -TimeoutSec 15
    if (-not $impResp.ok) {
        throw "Folder upload failed: $($impResp | ConvertTo-Json -Compress)"
    }
    Write-Host "[PASS] Local .SemanticModel uploaded & Portal generated: $($impResp.model_name)"

    # 5. Verify Portal Index, embedded Mermaid asset, and generated Semantic Model HTML page
    $portalHome = Invoke-WebRequest -Uri "$baseUrl/portal/index.html" -UseBasicParsing -TimeoutSec 5
    if ($portalHome.Content -notmatch "RetailAnalytics" -or $portalHome.Content -notmatch "sql-prod\.contoso\.local") {
        throw "Generated Portal index.html missing imported model or lineage source!"
    }
    $mermaidResp = Invoke-WebRequest -Uri "$baseUrl/portal/assets/mermaid.min.js" -UseBasicParsing -TimeoutSec 5
    if ($mermaidResp.RawContentLength -lt 100000) {
        throw "Embedded mermaid.min.js too small ($($mermaidResp.RawContentLength) bytes)!"
    }
    $modelHtmlFiles = Get-ChildItem -Path (Join-Path $catalogDir "portal\models") -Filter "*.html"
    if ($modelHtmlFiles.Count -lt 1) {
        throw "No model HTML page generated in portal/models!"
    }
    $modelPageResp = Invoke-WebRequest -Uri "$baseUrl/portal/models/$($modelHtmlFiles[0].Name)" -UseBasicParsing -TimeoutSec 5
    if ($modelPageResp.Content -notmatch "Total Revenue" -or $modelPageResp.Content -notmatch "Avg Revenue per Customer") {
        throw "Model HTML page missing expected DAX measures!"
    }
    Write-Host "[PASS] Generated Portal HTML + Star-Schema + DAX catalog + embedded Mermaid JS ($($mermaidResp.RawContentLength) bytes) verified"

    # 6. Verify pbixray native C-extension fails gracefully on invalid .pbix (proving pbixray DLLs imported cleanly without ImportError)
    $dummyBytes = [System.Text.Encoding]::ASCII.GetBytes("NOT_A_REAL_PBIX")
    $pbixResp = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/upload-local-file?name=invalid_test.pbix" -Body $dummyBytes -ContentType "application/octet-stream" -TimeoutSec 10
    if ($pbixResp.error -match "No module named|DLL load failed|ImportError") {
        throw "PBIXRay binary/DLL packaging error inside EXE: $($pbixResp.error)"
    }
    Write-Host "[PASS] PBIXRay native C-extension imported cleanly inside frozen EXE (graceful message: $($pbixResp.error))"

    # 7. Verify MCP stdio server inside frozen EXE
    $mcpInput = @(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"pbi_list_models","arguments":{}}}'
    ) -join "`n"
    $mcpOut = $mcpInput | & $exePath mcp --catalog $catalogDir 2>&1 | Out-String
    if ($mcpOut -notmatch "RetailAnalytics" -or $mcpOut -notmatch "protocolVersion") {
        throw "MCP stdio server check failed: $mcpOut"
    }
    Write-Host "[PASS] Built-in MCP stdio server responded cleanly from frozen EXE"

    Write-Host "=== ALL PORTABLE EXE E2E CHECKS PASSED 100% ==="
}
finally {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Pop-Location -ErrorAction SilentlyContinue
    $env:PATH = $origPath
    $env:PYTHONHOME = $origPyHome
    $env:PYTHONPATH = $origPyPath
    Remove-Item -Recurse -Force $workRoot -ErrorAction SilentlyContinue
}
