@echo off
REM 创建并配置 Python 虚拟环境
REM 在项目根目录运行

echo [1/3] 创建虚拟环境...
python -m venv .venv

echo [2/3] 激活虚拟环境并安装依赖...
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt

echo [3/3] 验证安装...
python -c "import requests, yaml, openai, anthropic, feedparser, arxiv; print('所有依赖安装成功 ✓')"

echo.
echo ====================================
echo 安装完成！
echo.
echo 下一步：
echo   1. 编辑 .env 填入 API Key
echo   2. 编辑 config.yaml 调整配置
echo   3. 运行 python main.py --dry-run 测试
echo ====================================
pause
