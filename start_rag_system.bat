@echo off
chcp 65001 >nul
title RAG System Launcher

echo ========================================
echo    RAG系统启动器
echo ========================================
echo.
echo [1] 主工作台 (front_pgui.py)
echo [2] 知识召回窗口 (pgirecallwindow.py)
echo [3] RAG前端 (RAG_Frontend.py)
echo [4] BGE向量化工具 (bge_gui.py)
echo [5] API配置测试 (test_api_config.py)
echo [0] 退出
echo.
echo ========================================
set /p choice="请选择要启动的模块 (0-5): "

if "%choice%"=="1" goto start_front
if "%choice%"=="2" goto start_recall
if "%choice%"=="3" goto start_rag
if "%choice%"=="4" goto start_bge
if "%choice%"=="5" goto test_api
if "%choice%"=="0" goto end
goto invalid

:start_front
echo.
echo [启动] 主工作台 (front_pgui.py)...
echo.
python front_pgui.py
goto end

:start_recall
echo.
echo [启动] 知识召回窗口 (pgirecallwindow.py)...
echo.
python pgirecallwindow.py
goto end

:start_rag
echo.
echo [启动] RAG前端 (RAG_Frontend.py)...
echo.
python RAG_Frontend.py
goto end

:start_bge
echo.
echo [启动] BGE向量化工具 (bge_gui.py)...
echo.
python bge_gui.py
goto end

:test_api
echo.
echo [测试] API配置测试...
echo.
python test_api_config.py
pause
goto end

:invalid
echo.
echo [错误] 无效的选择,请重新运行脚本。
pause
goto end

:end
echo.
echo 程序已关闭。
pause
