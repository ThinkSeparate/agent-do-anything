@echo off
chcp 65001 >nul
echo 激活conda环境并运行pipreqs（不指定版本）...

call conda activate pytorch_gpu_py310

pipreqs . --encoding=utf8 --force --ignore=agent_output,try_framework,output,dist

if errorlevel 1 (
    echo 生成失败！
    pause
    exit /b 1
)

echo 成功生成requirements.txt！

pause