@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Game Event Solver v18 - Visible Install Progress
set "LOG=%~dp0startup.log"
set "VENV=%~dp0.python_env"
set "VPY=%VENV%\Scripts\python.exe"
echo ================================================================
echo Game Event Solver v18 - Python 3.9+ Local
echo Directory: "%CD%"
echo ================================================================
echo.
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.9 -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3.9"
)
if not defined PYCMD (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYCMD=py -3"
    )
)
if not defined PYCMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYCMD=python"
    )
)
if not defined PYCMD (
    echo ERROR: Python 3.9+ not found by py launcher or PATH.
    goto failed
)
echo Using Python: %PYCMD%
%PYCMD% --version
%PYCMD% -c "import struct;print('Python bits:',struct.calcsize('P')*8)"
if errorlevel 1 goto failed
%PYCMD% -c "import struct,sys;sys.exit(0 if struct.calcsize('P')*8==64 else 1)" >nul 2>nul
if errorlevel 1 (
    echo ERROR: 64-bit Python is required for this starter pack.
    goto failed
)
echo.
echo Trying installed NumPy and SciPy before any downloads...
%PYCMD% -c "import numpy,scipy;from scipy.optimize import milp;print('Using installed NumPy',numpy.__version__,'SciPy',scipy.__version__)" 
if not errorlevel 1 (
    goto start_server_global
)
echo.
echo No compatible packages in the installed Python; using isolated environment.
if not exist "%VPY%" (
    echo Creating isolated environment .python_env ...
    %PYCMD% -m venv "%VENV%" >"%LOG%" 2>&1
    if errorlevel 1 (
        echo ERROR: Environment creation failed. Details:
        type "%LOG%"
        goto failed
    )
)
"%VPY%" -u setup_deps.py
if errorlevel 1 goto failed
goto start_server_venv
:start_server_global
echo.
echo Using the installed Python - no dependency downloads needed.
echo Starting local server at http://127.0.0.1:18771/index.html
echo Keep this window open during use.
%PYCMD% -u local_solver_server.py
goto server_done
:start_server_venv
echo.
echo Starting local server at http://127.0.0.1:18771/index.html
echo Browser should open automatically. Keep this window open during use.
echo.
"%VPY%" -u local_solver_server.py
:server_done
set "RC=%errorlevel%"
echo Local server ended with exit code %RC%.
if not "%RC%"=="0" goto failed
goto finish
:failed
echo.
echo Startup failed. See pip_install.log or startup.log for details.
echo Please send the last lines of pip_install.log if it failed during setup.
:finish
echo.
pause
endlocal
