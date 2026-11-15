param([string]$Source, [string]$Destination, [string]$Audit)
$ErrorActionPreference = 'Stop'
function Read-Workbook($book) {
    if ($book.HasVBProject -or $book.Connections.Count -gt 0) { throw 'Unsupported active workbook content' }
    $sheets = @()
    $total = 0
    foreach ($sheet in $book.Sheets) {
        if ($sheet.Type -ne -4167 -or $sheet.QueryTables.Count -gt 0) { throw 'Only ordinary worksheets are supported' }
        $range = $sheet.UsedRange
        if ([double]$range.Rows.Count * [double]$range.Columns.Count -gt 100000) { throw 'Worksheet cell budget exceeded' }
        $cells = @()
        foreach ($cell in $range.Cells) {
            $total++
            if ($total -gt 100000) { throw 'Workbook cell budget exceeded' }
            $value = $cell.Value2
            $formula = if ($cell.HasFormula) { [string]$cell.Formula } else { $null }
            if ($null -eq $value -and $null -eq $formula) { continue }
            if ($value -is [System.Runtime.InteropServices.ErrorWrapper]) { throw 'Error cells require manual review' }
            $cells += @{address=$cell.Address($false,$false); value=$value; formula=$formula; number_format=[string]$cell.NumberFormat}
        }
        $visibility = if ($sheet.Visible -eq -1) { 0 } elseif ($sheet.Visible -eq 0) { 1 } else { 2 }
        $sheets += @{name=[string]$sheet.Name; visibility=$visibility; cells=@($cells); shapes=[int]$sheet.Shapes.Count}
    }
    return @{date1904=[bool]$book.Date1904; sheets=@($sheets); names=[int]$book.Names.Count}
}
$existingExcel = @(Get-Process EXCEL -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$excel = New-Object -ComObject Excel.Application
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class ExcelProcess { [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId); }'
[uint32]$excelProcessId = 0
[void][ExcelProcess]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd, [ref]$excelProcessId)
$ownedProcess = Get-Process -Id $excelProcessId
@{pid=$excelProcessId; started=$ownedProcess.StartTime.ToUniversalTime().Ticks.ToString(); owned=($excelProcessId -notin $existingExcel)} | ConvertTo-Json | Set-Content -LiteralPath ($Audit + '.process.json') -Encoding UTF8
$excel.Visible = $false
$excel.DisplayAlerts = $false
$excel.EnableEvents = $false
$excel.AskToUpdateLinks = $false
$excel.AutomationSecurity = 3
$book = $null
$seed = $null
try {
    $seed = $excel.Workbooks.Add()
    $excel.Calculation = -4135
    $excel.CalculateBeforeSave = $false
    $book = $excel.Workbooks.Open($Source,0,$true,5,'','',$true)
    $before = Read-Workbook $book
    $book.CheckCompatibility = $false
    $book.SaveAs($Destination,51)
    $book.Close($false)
    $book = $null
    $excel.AutomationSecurity = 3
    $book = $excel.Workbooks.Open($Destination,0,$true,5,'','',$true)
    $after = Read-Workbook $book
    @{before=$before; after=$after; engine='Microsoft Excel'; version=[string]$excel.Version;
      controls=@{automation_security=3; update_links=0; events=$false; calculation='manual'; calculate_before_save=$false; source_read_only=$true}} |
      ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Audit -Encoding UTF8
} finally {
    if ($null -ne $book) { $book.Close($false) }
    if ($null -ne $seed) { $seed.Close($false) }
    $excel.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
}
