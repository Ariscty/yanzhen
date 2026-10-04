<#
    YanZhen - store screenshot prepper
    ==================================
    Turns a raw screenshot into a store-ready 1280x800 PNG, and optionally
    blacks out a rectangle (for masking anything private).

    ASCII-only on purpose: this is a .ps1 that may be run via
    `powershell.exe -File`, and non-ASCII text in a BOM-less .ps1 gets mangled.

    Usage:
      powershell -ExecutionPolicy Bypass -File store\prep_screenshot.ps1 `
          -In shot.png -Out store\screenshots\01-main.png

      # crop a specific 1280x800 window at 1:1 (best quality - no downscaling)
      powershell ... -In shot.png -Out out.png -CropX 300 -CropY 120

      # black out a rectangle before saving
      powershell ... -In shot.png -Out out.png -MaskX 40 -MaskY 500 -MaskW 300 -MaskH 60
#>
param(
    [Parameter(Mandatory=$true)][string]$In,
    [Parameter(Mandatory=$true)][string]$Out,
    [int]$CropX = -1,
    [int]$CropY = -1,
    [int]$MaskX = -1,
    [int]$MaskY = -1,
    [int]$MaskW = 0,
    [int]$MaskH = 0,
    [switch]$Blur          # blur the mask rectangle instead of filling black
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$W = 1280; $H = 800

if (-not (Test-Path $In)) { throw "input not found: $In" }

$src = [System.Drawing.Image]::FromFile((Resolve-Path $In))
Write-Host ("input : {0}  ({1} x {2})" -f (Split-Path $In -Leaf), $src.Width, $src.Height)

# ---- decide the source rectangle -------------------------------------------
if ($CropX -ge 0 -and $CropY -ge 0) {
    $sx = $CropX; $sy = $CropY
    if ($sx + $W -gt $src.Width -or $sy + $H -gt $src.Height) {
        throw ("crop {0},{1} +{2}x{3} goes outside the image ({4}x{5})" -f `
               $sx, $sy, $W, $H, $src.Width, $src.Height)
    }
    Write-Host ("crop  : {0},{1} {2}x{3} at 1:1 (no rescaling)" -f $sx, $sy, $W, $H)
} else {
    # center the biggest possible 16:10 box, then rescale
    $sx = [int](($src.Width  - [math]::Min($src.Width,  $src.Height * 16 / 10)) / 2)
    $sy = [int](($src.Height - [math]::Min($src.Height, $src.Width  * 10 / 16)) / 2)
    $sw = [math]::Min($src.Width  - $sx, [int]($src.Height * 16 / 10))
    $sh = [math]::Min($src.Height - $sy, [int]($src.Width  * 10 / 16))
    Write-Host ("crop  : center {0},{1} {2}x{3} then rescale to {4}x{5}" -f $sx, $sy, $sw, $sh, $W, $H)
}

$bmp = New-Object System.Drawing.Bitmap $W, $H
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.PixelOffsetMode   = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$g.Clear([System.Drawing.Color]::White)

if ($CropX -ge 0 -and $CropY -ge 0) {
    $dst = New-Object System.Drawing.Rectangle 0, 0, $W, $H
    $srect = New-Object System.Drawing.Rectangle $sx, $sy, $W, $H
    $g.DrawImage($src, $dst, $srect, [System.Drawing.GraphicsUnit]::Pixel)
} else {
    $dst = New-Object System.Drawing.Rectangle 0, 0, $W, $H
    $srect = New-Object System.Drawing.Rectangle $sx, $sy, $sw, $sh
    $g.DrawImage($src, $dst, $srect, [System.Drawing.GraphicsUnit]::Pixel)
}
$g.Dispose()

# ---- optional masking -------------------------------------------------------
if ($MaskX -ge 0 -and $MaskY -ge 0 -and $MaskW -gt 0 -and $MaskH -gt 0) {
    if ($Blur) {
        # box blur by repeated downscale+upscale of that region
        $region = New-Object System.Drawing.Rectangle $MaskX, $MaskY, $MaskW, $MaskH
        $tmp = New-Object System.Drawing.Bitmap 64, [int](64 * $MaskH / $MaskW)
        $gt = [System.Drawing.Graphics]::FromImage($tmp)
        $gt.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $gt.DrawImage($bmp, (New-Object System.Drawing.Rectangle 0,0,$tmp.Width,$tmp.Height), $region, [System.Drawing.GraphicsUnit]::Pixel)
        $gt.Dispose()
        $g2 = [System.Drawing.Graphics]::FromImage($bmp)
        $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g2.DrawImage($tmp, $region)
        $g2.Dispose(); $tmp.Dispose()
        Write-Host ("mask  : blurred {0},{1} {2}x{3}" -f $MaskX, $MaskY, $MaskW, $MaskH)
    } else {
        $g3 = [System.Drawing.Graphics]::FromImage($bmp)
        $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::Black)
        $g3.FillRectangle($brush, $MaskX, $MaskY, $MaskW, $MaskH)
        $g3.Dispose(); $brush.Dispose()
        Write-Host ("mask  : filled black {0},{1} {2}x{3}" -f $MaskX, $MaskY, $MaskW, $MaskH)
    }
}

# ---- save -------------------------------------------------------------------
$dir = Split-Path $Out -Parent
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$bmp.Save((Join-Path (Get-Location) $Out), [System.Drawing.Imaging.ImageFormat]::Png)
$size = (Get-Item $Out).Length
Write-Host ("output: {0}  {1}x{2}  {3:N0} bytes" -f $Out, $W, $H, $size)
$bmp.Dispose(); $src.Dispose()
Write-Host "OK"
