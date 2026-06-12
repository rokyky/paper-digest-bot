@echo off
REM 注册 Windows 定时任务（每天 9:00 运行）
REM 以管理员身份运行
REM
REM 用法：schedule_windows.bat [时间]
REM   默认 09:00
REM   示例：schedule_windows.bat 08:30

setlocal

set PROJECT_DIR=%~dp0..
set TASK_NAME=PaperDigestBot
set PYTHON_PATH=%PROJECT_DIR%\.venv\Scripts\python.exe
set MAIN_PATH=%PROJECT_DIR%\main.py

if "%1"=="" (
    set START_TIME=09:00
) else (
    set START_TIME=%1
)

echo 注册 Windows 定时任务...
echo 项目目录: %PROJECT_DIR%
echo 执行时间: 每天 %START_TIME%
echo 脚本: %PYTHON_PATH% %MAIN_PATH%

schtasks /create /tn "%TASK_NAME%" /tr "%PYTHON_PATH% %MAIN_PATH%" /sc daily /st %START_TIME% /f

if %ERRORLEVEL% equ 0 (
    echo.
    echo ✅ 定时任务注册成功！
    echo 任务名: %TASK_NAME%
    echo 执行时间: 每天 %START_TIME%
    echo.
    echo 查看任务: 在 "任务计划程序" 中查看
    echo 手动运行: schtasks /run /tn "%TASK_NAME%"
    echo 停止任务: schtasks /end /tn "%TASK_NAME%"
    echo 删除任务: schtasks /delete /tn "%TASK_NAME%" /f
) else (
    echo.
    echo ❌ 定时任务注册失败
    echo 请以管理员身份运行此脚本
)

pause
