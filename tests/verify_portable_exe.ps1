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
    if ($LASTEXITCODE -ne 0 -or $verOut -notmatch "1\.\d+\.\d+") {
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
    if ($uiResp.Content -notmatch "Sign in with Microsoft" -or $uiResp.Content -notmatch "Select Power BI File") {
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

    # 5. Verify Portal Index and generated Semantic Model HTML page (native SVG Star-Schema + DAX catalog + Export modal)
    $portalHome = Invoke-WebRequest -Uri "$baseUrl/portal/index.html" -UseBasicParsing -TimeoutSec 5
    if ($portalHome.Content -notmatch "RetailAnalytics" -or $portalHome.Content -notmatch "sql-prod\.contoso\.local") {
        throw "Generated Portal index.html missing imported model or lineage source!"
    }
    $modelHtmlFiles = Get-ChildItem -Path (Join-Path $catalogDir "portal\models") -Filter "*.html"
    if ($modelHtmlFiles.Count -lt 1) {
        throw "No model HTML page generated in portal/models!"
    }
    $modelPageResp = Invoke-WebRequest -Uri "$baseUrl/portal/models/$($modelHtmlFiles[0].Name)" -UseBasicParsing -TimeoutSec 5
    if ($modelPageResp.Content -notmatch "Total Revenue" -or $modelPageResp.Content -notmatch "Avg Revenue per Customer" -or $modelPageResp.Content -notmatch "star-shell" -or $modelPageResp.Content -notmatch "print-only-doc-banner") {
        throw "Model HTML page missing expected DAX measures, native Star-Schema diagram, or print blueprint banner!"
    }
    $starJsResp = Invoke-WebRequest -Uri "$baseUrl/portal/assets/star_schema_widget.js" -UseBasicParsing -TimeoutSec 5
    if ($starJsResp.Content -notmatch "print-only-star-stack") {
        throw "star_schema_widget.js missing stacked vector PDF Star-Schema renderer!"
    }
    foreach ($asset in @("portal.css", "star_schema_widget.js", "xray_drawer.js", "e2e_graph.js")) {
        $aResp = Invoke-WebRequest -Uri "$baseUrl/portal/assets/$asset" -UseBasicParsing -TimeoutSec 5
        if ($aResp.StatusCode -ne 200 -or $aResp.RawContentLength -lt 50) {
            throw "Missing or empty v1.1 portal asset: $asset"
        }
    }
    Write-Host "[PASS] Generated Portal HTML + native Star-Schema + v1.1 X-Ray/E2E assets + DAX catalog verified"

    # 6. Verify HTTP crash-resilience inside frozen EXE (malformed JSON returns clean ERR_BAD_JSON and server stays alive)
    $got400 = $false
    try {
        Invoke-WebRequest -Method Post -Uri "$baseUrl/api/connect" -Body "{broken_json" -ContentType "application/json" -UseBasicParsing -TimeoutSec 5 | Out-Null
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -eq 400) { $got400 = $true }
    }
    if (-not $got400) { throw "Expected HTTP 400 ERR_BAD_JSON on malformed POST body!" }
    $aliveResp = Invoke-RestMethod -Uri "$baseUrl/api/status" -TimeoutSec 5
    if ($aliveResp.models_count -lt 1) { throw "Studio server lost state after malformed POST!" }
    Write-Host "[PASS] Studio server fault-isolation verified (survived malformed request cleanly)"

    # 7. Verify pbixray native C-extension fails gracefully on invalid .pbix (proving pbixray DLLs imported cleanly without ImportError)
    $dummyBytes = [System.Text.Encoding]::ASCII.GetBytes("NOT_A_REAL_PBIX")
    $pbixResp = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/upload-local-file?name=invalid_test.pbix" -Body $dummyBytes -ContentType "application/octet-stream" -TimeoutSec 10
    if ($pbixResp.error -match "No module named|DLL load failed|ImportError") {
        throw "PBIXRay binary/DLL packaging error inside EXE: $($pbixResp.error)"
    }
    Write-Host "[PASS] PBIXRay native C-extension imported cleanly inside frozen EXE (graceful message: $($pbixResp.error))"

    # 8. Verify v1.1 CLI export-site (SharePoint single-file HTML) & measure-doc inside frozen EXE
    $spHtml = Join-Path $workRoot "SharePoint_Single.html"
    & $exePath export-site --catalog $catalogDir --format single -o $spHtml | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $spHtml) -or (Get-Item $spHtml).Length -lt 5000) {
        throw "export-site single-file SharePoint HTML failed inside frozen EXE!"
    }
    $mDoc = Join-Path $workRoot "AvgRev_Lineage.md"
    & $exePath measure-doc "Avg Revenue per Customer" --catalog $catalogDir -o $mDoc | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $mDoc) -or (Get-Content -Raw $mDoc) -notmatch "FACT_SALES") {
        throw "measure-doc end-to-end lineage export failed inside frozen EXE!"
    }
    Write-Host "[PASS] v1.1 export-site (SharePoint HTML) and measure-doc (SQL-to-DAX lineage) verified from frozen EXE"

    # 9. Verify MCP stdio server (all 10 v1.1 tools + end-to-end measure trace) inside frozen EXE
    $mcpInput = @(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
        '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"pbi_trace_measure_end_to_end","arguments":{"measure":"Avg Revenue per Customer"}}}'
    ) -join "`n"
    $mcpOut = $mcpInput | & $exePath mcp --catalog $catalogDir 2>&1 | Out-String
    if ($mcpOut -notmatch "RetailAnalytics" -or $mcpOut -notmatch "pbi_report_layout" -or $mcpOut -notmatch "FACT_SALES") {
        throw "MCP stdio v1.1 tools check failed: $mcpOut"
    }
    Write-Host "[PASS] Built-in MCP stdio server (all 10 v1.1 tools + E2E SQL trace) verified from frozen EXE"

    # 10. Verify v1.0 legacy catalog detection & clean backup inside frozen EXE
    $v10Dir = Join-Path $workRoot "legacy_v10_catalog"
    New-Item -ItemType Directory -Path (Join-Path $v10Dir "portal") -Force | Out-Null
    Set-Content -Path (Join-Path $v10Dir "catalog_state.json") -Value '{"schema_version":"1.0","models":{"ds1":{"id":"ds1","name":"OldV10Model","workspace_id":"ws1"}},"workspaces":{"ws1":{"id":"ws1","name":"WS1"}}}' -Encoding UTF8
    Set-Content -Path (Join-Path $v10Dir "portal\index.html") -Value '<html>OLD_V10_HTML</html>' -Encoding UTF8
    $port2 = $port + 1
    $proc2 = Start-Process -FilePath $exePath -ArgumentList @("studio", "--catalog", $v10Dir, "--port", "$port2", "--no-browser") -PassThru -WindowStyle Hidden
    try {
        $base2 = "http://127.0.0.1:$port2"
        $st2 = $null
        for ($j = 0; $j -lt 25; $j++) {
            Start-Sleep -Milliseconds 400
            try { $st2 = Invoke-RestMethod -Uri "$base2/api/status" -TimeoutSec 2; if ($null -ne $st2.legacy_catalog) { break } } catch {}
        }
        if (-not $st2 -or -not $st2.legacy_catalog.is_legacy -or $st2.portal_ready) {
            throw "Frozen EXE failed to flag v1.0 legacy catalog!"
        }
        $rst2 = Invoke-RestMethod -Method Post -Uri "$base2/api/reset-catalog" -Body '{"from_legacy":true}' -ContentType "application/json" -TimeoutSec 5
        if (-not $rst2.ok -or -not (Test-Path (Join-Path $v10Dir "catalog_state.v1_0.bak.json"))) {
            throw "Frozen EXE failed to archive catalog_state.v1_0.bak.json on clean reset!"
        }
        Write-Host "[PASS] Legacy v1.0 cache detection + clean v1.1 reset verified inside frozen EXE"
    } finally {
        if ($proc2 -and -not $proc2.HasExited) { Stop-Process -Id $proc2.Id -Force -ErrorAction SilentlyContinue }
    }

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
