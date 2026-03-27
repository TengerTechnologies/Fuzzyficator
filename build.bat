@echo off
echo ============================================
echo  Fuzzyficator GUI - Build Standalone .exe
echo ============================================
echo.
echo This will create a single .exe file in the dist\ folder
echo that includes the GUI and all dependencies.
echo.
echo Requirements: Python 3.7+ and PyInstaller
echo   pip install pyinstaller customtkinter
echo.
pause

pyinstaller --onefile --windowed --name "FuzzyficatorGUI" --collect-all customtkinter --add-data "fuzzyficator_core.py;." FuzzyficatorGUI.py

echo.
if exist "dist\FuzzyficatorGUI.exe" (
    echo Build successful! Your .exe is at:
    echo   dist\FuzzyficatorGUI.exe
    echo.
    echo You can distribute this single file - no Python needed to run it.
) else (
    echo Build may have failed. Check the output above for errors.
)
echo.
pause
