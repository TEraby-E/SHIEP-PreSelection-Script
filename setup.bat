@echo off
echo === Multi-IP Cookie Scanner Setup ===
echo.

echo Installing Python dependencies...
pip install playwright pyyaml rich
echo.

echo Installing Chromium browser...
playwright install chromium
echo.

echo Copying example config...
if not exist config.yaml (
    copy config.example.yaml config.yaml
    echo Created config.yaml - please edit it with your accounts!
) else (
    echo config.yaml already exists, skipping.
)

echo.
echo === Setup complete! ===
echo Edit config.yaml, then run: python -m src.main -c config.yaml
pause
