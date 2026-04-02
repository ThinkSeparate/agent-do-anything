#!/usr/bin/env python3
"""
打包脚本 - 用于将项目打包成可执行文件
适用于 Windows 环境
"""

import os
import sys
import shutil
import subprocess
import tempfile
import zipfile
import venv
from pathlib import Path
import json

def run_command(cmd, cwd=None, shell=True, check=True):
    """运行命令并检查返回码"""
    print(f"运行命令: {cmd}")
    result = subprocess.run(cmd, shell=shell, cwd=cwd, capture_output=True, text=True)
    
    if check and result.returncode != 0:
        print(f"命令失败: {result.stderr}")
        raise RuntimeError(f"命令执行失败: {cmd}")
    
    if result.stdout:
        print(f"输出: {result.stdout}")
    
    return result

def is_git_repo():
    """检查当前目录是否是git仓库"""
    git_dir = Path(".git")
    return git_dir.exists() and git_dir.is_dir()

def clear_output_dir(output_dir):
    """清空输出目录，如果存在则删除并重新创建"""
    output_path = Path(output_dir)
    
    if output_path.exists():
        print(f"清空输出目录: {output_dir}")
        shutil.rmtree(output_path)
    
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path

def git_archive_to_zip(output_path):
    """使用git archive打包当前仓库到zip文件"""
    if not is_git_repo():
        raise RuntimeError("当前目录不是git仓库")
    
    # 生成临时zip文件名
    temp_zip = output_path / "temp_archive.zip"
    
    # 获取当前分支名
    try:
        result = run_command("git rev-parse --abbrev-ref HEAD", check=False)
        branch_name = result.stdout.strip() if result.returncode == 0 else "HEAD"
    except:
        # 如果获取分支名失败，使用HEAD
        branch_name = "HEAD"
    
    print(f"当前分支: {branch_name}")
    
    # 使用git archive打包
    archive_cmd = f'git archive --format=zip --output="{temp_zip}" {branch_name}'
    run_command(archive_cmd)
    
    return temp_zip

def extract_zip(zip_path, extract_to):
    """解压zip文件到指定目录"""
    print(f"解压文件: {zip_path} -> {extract_to}")
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    
    # 删除临时zip文件
    zip_path.unlink()
    print("解压完成")

def copy_requirements_to_output(output_dir, source_dir="."):
    """复制requirements.txt到输出目录"""
    source_req = Path(source_dir) / "requirements.txt"
    dest_req = Path(output_dir) / "requirements.txt"
    
    if source_req.exists():
        shutil.copy2(source_req, dest_req)
        print(f"已复制: {source_req} -> {dest_req}")
    else:
        print(f"警告: 未找到 {source_req}")
        # 如果没有requirements.txt，创建一个基本的
        with open(dest_req, 'w') as f:
            f.write("# 项目依赖\n")
            f.write("pyyaml\n")
            f.write("openai\n")
            f.write("requests\n")
        print(f"已创建基本 requirements.txt")

def create_clean_venv_for_build(output_dir):
    """为打包创建一个干净的虚拟环境，只安装requirements.txt中的包"""
    print("创建干净的虚拟环境用于打包...")
    
    # 创建虚拟环境目录
    venv_dir = Path(output_dir) / "_build_venv"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    
    # 创建虚拟环境
    print(f"创建虚拟环境: {venv_dir}")
    venv.create(venv_dir, with_pip=True, clear=True)
    
    # 获取虚拟环境中的Python路径
    if sys.platform == "win32":
        python_exe = venv_dir / "Scripts" / "python.exe"
        pip_exe = venv_dir / "Scripts" / "pip.exe"
    else:
        python_exe = venv_dir / "bin" / "python"
        pip_exe = venv_dir / "bin" / "pip"
    
    # 检查虚拟环境中的Python是否可用
    if not python_exe.exists():
        raise FileNotFoundError(f"虚拟环境Python不存在: {python_exe}")
    
    # 升级pip - 使用python -m pip方式，避免Windows上的权限问题
    print("升级pip...")
    # 注意：这里使用python -m pip install --upgrade pip而不是直接调用pip.exe
    run_command(f'"{python_exe}" -m pip install --upgrade pip')
    
    # 安装requirements.txt中的依赖
    req_file = Path(output_dir) / "requirements.txt"
    if req_file.exists():
        print(f"安装requirements.txt中的依赖: {req_file}")
        # 同样使用python -m pip方式安装依赖
        run_command(f'"{python_exe}" -m pip install -r "{req_file}"')
    else:
        print("警告: 未找到requirements.txt，安装基本依赖")
        run_command(f'"{python_exe}" -m pip install pyyaml openai requests')
    
    # 安装PyInstaller
    print("安装PyInstaller...")
    run_command(f'"{python_exe}" -m pip install pyinstaller')
    
    return python_exe, pip_exe

def build_exe_with_pyinstaller(output_dir, python_exe=None):
    """使用PyInstaller打包可执行文件"""
    print("开始使用PyInstaller打包...")
    
    # 使用指定的Python解释器，如果未指定则使用当前解释器
    if python_exe is None:
        python_exe = sys.executable
    
    # 检查agent.spec是否存在
    spec_file = Path(output_dir) / "agent.spec"
    if spec_file.exists():
        # 使用spec文件构建
        print(f"使用spec文件构建: {spec_file}")
        build_cmd = f'"{python_exe}" -m PyInstaller "{spec_file}" --distpath "{output_dir}/dist" --workpath "{output_dir}/build" --clean'
    else:
        # 如果没有spec文件，直接构建agent.py
        print("使用agent.py直接构建")
        agent_file = Path(output_dir) / "agent.py"
        if not agent_file.exists():
            raise FileNotFoundError(f"未找到agent.py文件: {agent_file}")
        
        # 构建命令
        build_cmd = f'"{python_exe}" -m PyInstaller "{agent_file}" --onefile --name "agent" --distpath "{output_dir}/dist" --workpath "{output_dir}/build" --clean'
    
    try:
        run_command(build_cmd, cwd=output_dir)
        print("PyInstaller打包完成")
    except Exception as e:
        print(f"PyInstaller打包失败: {e}")
        # 尝试使用备用方法
        print("尝试备用打包方法...")
        try:
            # 如果spec文件存在但构建失败，尝试使用agent.py直接构建
            backup_cmd = f'"{python_exe}" -m PyInstaller "{agent_file}" --onefile --name "agent" --distpath "{output_dir}/dist" --workpath "{output_dir}/build"'
            run_command(backup_cmd, cwd=output_dir)
            print("备用打包方法成功")
        except Exception as e2:
            print(f"备用打包方法也失败: {e2}")
            raise

def create_install_script(output_dir):
    """创建一个安装/运行脚本"""
    script_content = '''@echo off
chcp 65001 >nul
REM 自动生成的运行脚本
echo 正在启动Agent...

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.8或更高版本
    echo 可以从 https://www.python.org/downloads/ 下载
    pause
    exit /b 1
)

REM 检查Python版本
for /f "tokens=2" %%i in ('python -c "import sys; print(sys.version)"') do set "python_version=%%i"
for /f "tokens=1,2 delims=. " %%i in ("%python_version%") do (
    if %%i LSS 3 (
        echo 错误: 需要Python 3.8或更高版本，当前版本: %python_version%
        pause
        exit /b 1
    )
    if %%i EQU 3 if %%j LSS 8 (
        echo 错误: 需要Python 3.8或更高版本，当前版本: %python_version%
        pause
        exit /b 1
    )
)

REM 安装依赖
echo 正在安装依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo 依赖安装失败，请检查网络连接和requirements.txt文件
    pause
    exit /b 1
)

REM 检查配置文件
if not exist "config.yaml" (
    echo 警告: 未找到config.yaml配置文件
    echo 正在从config.example.yaml创建配置文件...
    if exist "config.example.yaml" (
        copy "config.example.yaml" "config.yaml" >nul
        echo 已创建config.yaml，请根据需要进行配置
    ) else (
        echo 错误: 未找到配置文件模板config.example.yaml
    )
)

REM 运行主程序
echo 启动主程序...
python agent.py
if errorlevel 1 (
    echo 程序运行失败
    pause
    exit /b 1
)
pause
'''
    
    script_path = Path(output_dir) / "install_and_run.bat"
    with open(script_path, 'w', encoding='gbk') as f:  # 使用GBK编码以兼容中文Windows
        f.write(script_content)
    
    # 设置文件属性
    os.chmod(script_path, 0o755)
    print(f"已创建安装脚本: {script_path}")

def copy_config_files(output_dir, source_dir="."):
    """复制配置文件到输出目录"""
    print("复制配置文件...")
    
    config_files = ["config.yaml", "config.example.yaml", ".env.example"]
    
    for config_file in config_files:
        source_path = Path(source_dir) / config_file
        dest_path = Path(output_dir) / config_file
        
        if source_path.exists() and not dest_path.exists():
            shutil.copy2(source_path, dest_path)
            print(f"已复制配置文件: {config_file}")

def create_standalone_package(output_dir, source_dir="."):
    """创建独立运行的包，包含所有必要文件"""
    print("创建独立运行包...")
    
    # 复制配置文件
    copy_config_files(output_dir, source_dir)
    
    # 创建必要的目录结构
    dirs_to_create = ["logs", "agent_output", "config", "core", "utils"]
    for dir_name in dirs_to_create:
        dir_path = Path(output_dir) / dir_name
        dir_path.mkdir(exist_ok=True)
    
    # 创建README
    readme_content = """# Agent 程序

这是一个自动化的Agent程序。

## 快速开始

1. 确保已安装Python 3.8+
2. 运行 install_and_run.bat 安装依赖并启动
3. 或者手动运行: pip install -r requirements.txt && python agent.py

## 配置

请根据 config.yaml 文件中的注释进行配置。

## 注意事项

- 请确保网络连接正常
- 首次运行可能需要下载模型文件
"""
    
    with open(Path(output_dir) / "README.txt", 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    print("独立运行包创建完成")

def cleanup_build_artifacts(output_dir):
    """清理构建过程中产生的中间文件"""
    print("清理构建中间文件...")
    
    # 删除虚拟环境
    venv_dir = Path(output_dir) / "_build_venv"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
        print(f"已删除虚拟环境: {venv_dir}")
    
    # 删除build目录
    build_dir = Path(output_dir) / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print(f"已删除build目录: {build_dir}")
    
    # 删除spec文件
    spec_file = Path(output_dir) / "agent.spec"
    if spec_file.exists():
        spec_file.unlink()
        print(f"已删除spec文件: {spec_file}")

def create_final_zip(current_dir, output_dir):
    """创建最终的zip分发包"""
    print("创建最终分发包...")
    
    dist_dir = output_dir / "dist"
    if not dist_dir.exists():
        print("警告: 未找到dist目录，跳过创建zip包")
        return None
    
    exe_files = list(dist_dir.glob("*.exe"))
    if not exe_files:
        print("警告: 未找到可执行文件，跳过创建zip包")
        return None
    
    # 创建dist目录（用于存放最终的zip包）
    final_dist_dir = current_dir / "dist"
    final_dist_dir.mkdir(exist_ok=True)
    
    # 创建包含所有文件的zip
    final_zip = final_dist_dir / "agent_package.zip"
    
    with zipfile.ZipFile(final_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 添加可执行文件
        for exe in exe_files:
            zipf.write(exe, f"agent/{exe.name}")
            print(f"添加可执行文件: {exe.name}")
        
        # 添加配置文件
        config_files = [".yaml", ".txt", ".md", ".bat", ".env.example"]
        for file in output_dir.glob("*"):
            if file.is_file() and any(file.suffix.lower() == ext for ext in config_files):
                arcname = f"agent/{file.relative_to(output_dir)}"
                zipf.write(file, arcname)
                print(f"添加配置文件: {file.name}")
        
        # 添加requirements.txt
        req_file = output_dir / "requirements.txt"
        if req_file.exists():
            zipf.write(req_file, "agent/requirements.txt")
            print("添加requirements.txt")
        
        # 添加必要的目录
        for dir_name in ["logs", "agent_output"]:
            dir_path = output_dir / dir_name
            if dir_path.exists():
                for file_path in dir_path.rglob("*"):
                    if file_path.is_file():
                        arcname = f"agent/{dir_name}/{file_path.relative_to(dir_path)}"
                        zipf.write(file_path, arcname)
    
    print(f"✓ 打包完成! 最终包位置: {final_zip}")
    print(f"   大小: {final_zip.stat().st_size / 1024 / 1024:.2f} MB")
    
    return final_zip

def copy_config_example_to_dist(output_dir, source_dir="."):
    """将config.example.yaml复制到dist目录并重命名为config.yaml"""
    print("步骤12: 复制并重命名配置文件到dist目录")
    
    dist_dir = Path(output_dir) / "dist"
    if not dist_dir.exists():
        print("警告: dist目录不存在，正在创建")
        dist_dir.mkdir(parents=True, exist_ok=True)
    
    # 源文件路径
    config_example_source = Path(source_dir) / "config.example.yaml"
    
    # 如果当前目录没有config.example.yaml，尝试在output_dir中查找
    if not config_example_source.exists():
        config_example_source = Path(output_dir) / "config.example.yaml"
    
    if config_example_source.exists():
        # 目标文件路径
        config_target = dist_dir / "config.yaml"
        
        # 复制并重命名文件
        shutil.copy2(config_example_source, config_target)
        print(f"✓ 已复制并重命名: {config_example_source.name} -> {config_target.name}")
        
        # 确保文件有可读权限
        config_target.chmod(0o644)
        
        return config_target
    else:
        print("⚠ 警告: 未找到config.example.yaml文件")
        
        # 如果都没有，创建一个空的config.yaml
        config_target = dist_dir / "config.yaml"
        with open(config_target, 'w', encoding='utf-8') as f:
            f.write("# 请配置您的API密钥\n")
            f.write("model:\n")
            f.write("  api_key: \"sk-your-api-key-here\"\n")
            f.write("  base_url: \"https://api.deepseek.com/v1\"\n")
            f.write("  name: \"deepseek-reasoner\"\n")
        
        print(f"✓ 已创建默认配置文件: {config_target.name}")
        return config_target

def copy_user_manual_to_dist(output_dir, source_dir="."):
    """将用户手册复制到dist目录"""
    print("步骤13: 复制用户手册到dist目录")
    
    dist_dir = Path(output_dir) / "dist"
    if not dist_dir.exists():
        print("警告: dist目录不存在，正在创建")
        dist_dir.mkdir(parents=True, exist_ok=True)
    
    # 可能的用户手册文件名（按优先级尝试）
    manual_names = [
        "指导手册.docx",
        "用户手册.docx", 
        "使用指南.docx",
        "UserManual.docx",
        "README.docx",
        "instruction_manual.docx"
    ]
    
    manual_found = None
    manual_source = None
    
    # 首先在当前目录查找
    for manual_name in manual_names:
        test_path = Path(source_dir) / manual_name
        if test_path.exists():
            manual_found = manual_name
            manual_source = test_path
            break
    
    # 如果在当前目录没找到，在output_dir中查找
    if not manual_found:
        for manual_name in manual_names:
            test_path = Path(output_dir) / manual_name
            if test_path.exists():
                manual_found = manual_name
                manual_source = test_path
                break
    
    if manual_source and manual_found:
        # 目标文件路径 - 使用统一的文件名
        manual_target = dist_dir / "用户操作指南.docx"
        
        # 复制文件
        shutil.copy2(manual_source, manual_target)
        print(f"✓ 已复制用户手册: {manual_found} -> {manual_target.name}")
        
        # 确保文件有可读权限
        manual_target.chmod(0o644)
        
        return manual_target
    else:
        print("⚠ 警告: 未找到用户手册文件")
        
        # 如果没有找到，创建一个简单的文本说明文件
        txt_manual = dist_dir / "使用说明.txt"
        with open(txt_manual, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("智能助手 使用说明\n")
            f.write("=" * 60 + "\n\n")
            f.write("1. 配置说明\n")
            f.write("   - 请编辑 config.yaml 文件\n")
            f.write("   - 将 api_key 替换为您从 DeepSeek 获取的 API 密钥\n\n")
            f.write("2. 运行说明\n")
            f.write("   - 双击运行 agent.exe\n")
            f.write("   - 或通过命令行运行: agent.exe .\n\n")
            f.write("3. 获取 API 密钥\n")
            f.write("   - 访问: https://platform.deepseek.com\n")
            f.write("   - 注册账户并获取 API 密钥\n")
            f.write("   - 账户需要充值才能使用\n")
            f.write("=" * 60 + "\n")
        
        print(f"✓ 已创建文本说明文件: {txt_manual.name}")
        return txt_manual

def package_dist_files(current_dir, output_dir):
    """将dist目录下的文件打包成最终分发包"""
    print("步骤14: 打包dist目录文件")
    
    dist_dir = Path(output_dir) / "dist"
    if not dist_dir.exists():
        print("❌ 错误: dist目录不存在，无法打包")
        return None
    
    # 检查dist目录中是否有文件
    dist_files = list(dist_dir.glob("*"))
    if not dist_files:
        print("❌ 错误: dist目录为空，无法打包")
        return None
    
    print(f"dist目录中的文件:")
    for file in dist_files:
        if file.is_file():
            size_kb = file.stat().st_size / 1024
            print(f"  - {file.name} ({size_kb:.1f} KB)")
    
    # 创建最终分发包目录
    final_pkg_dir = current_dir / "dist"
    final_pkg_dir.mkdir(exist_ok=True)
    
    # 生成打包文件名（带时间戳）
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_name = f"agent_package_{timestamp}.zip"
    final_zip = final_pkg_dir / package_name
    
    # 创建zip文件
    with zipfile.ZipFile(final_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in dist_files:
            if file.is_file():
                # 将文件添加到zip的根目录（不包含dist目录结构）
                zipf.write(file, file.name)
                print(f"  添加: {file.name}")
    
    zip_size_mb = final_zip.stat().st_size / 1024 / 1024
    print(f"✓ 打包完成!")
    print(f"  包名: {package_name}")
    print(f"  大小: {zip_size_mb:.2f} MB")
    print(f"  位置: {final_zip}")
    
    # 同时创建一个不带时间戳的latest包（方便使用）
    latest_zip = final_pkg_dir / "agent_package_latest.zip"
    shutil.copy2(final_zip, latest_zip)
    print(f"  同时创建: agent_package_latest.zip")
    
    return final_zip

def main():
    """主函数"""
    print("=" * 60)
    print("开始打包 Agent 程序")
    print("=" * 60)
    
    # 设置路径
    current_dir = Path.cwd()
    output_dir = current_dir / "output"
    
    try:
        # 1. 清空输出目录
        print(f"步骤1: 准备输出目录: {output_dir}")
        clear_output_dir(output_dir)
        
        # 2. 使用git archive打包
        print("\n步骤2: 使用git archive打包")
        temp_zip = git_archive_to_zip(output_dir)
        
        # 3. 解压到output目录
        print("\n步骤3: 解压文件")
        extract_zip(temp_zip, output_dir)
        
        # 4. 复制requirements.txt
        print("\n步骤4: 复制依赖文件")
        copy_requirements_to_output(output_dir, current_dir)
        
        # 5. 创建干净的虚拟环境并安装依赖
        print("\n步骤5: 创建干净的虚拟环境并安装依赖")
        python_exe, pip_exe = create_clean_venv_for_build(output_dir)
        
        # 6. 使用虚拟环境中的Python打包
        print("\n步骤6: 在虚拟环境中打包可执行文件")
        build_exe_with_pyinstaller(output_dir, python_exe)
        
        # 7. 创建安装脚本
        print("\n步骤7: 创建安装脚本")
        create_install_script(output_dir)
        
        # 8. 复制配置文件
        print("\n步骤8: 复制配置文件")
        copy_config_files(output_dir, current_dir)
        
        # 9. 创建README
        print("\n步骤9: 创建独立运行包")
        create_standalone_package(output_dir, current_dir)
        
        # 10. 创建最终的zip分发包
        print("\n步骤10: 创建最终分发包")
        final_zip = create_final_zip(current_dir, output_dir)
        
        # 11. 清理中间文件
        print("\n步骤11: 清理中间文件")
        cleanup_build_artifacts(output_dir)
        
        # 12. 复制config.example.yaml到dist目录并重命名为config.yaml
        print("\n步骤12: 复制并重命名配置文件")
        config_file = copy_config_example_to_dist(output_dir, current_dir)
        
        # 13. 复制用户手册到dist目录
        print("\n步骤13: 复制用户手册")
        manual_file = copy_user_manual_to_dist(output_dir, current_dir)
        
        # 14. 打包dist目录文件
        print("\n步骤14: 创建最终分发包")
        final_zip = package_dist_files(current_dir, output_dir)
        
        # 原有的清理步骤（现在变为步骤15）
        print("\n步骤15: 清理中间文件")
        cleanup_build_artifacts(output_dir)
        
        print("\n" + "=" * 60)
        print("打包完成!")
        print("=" * 60)
        
        # 显示重要文件信息
        dist_dir = output_dir / "dist"
        if dist_dir.exists():
            print("\n生成的关键文件:")
            for file in dist_dir.glob("*"):
                if file.is_file():
                    size_mb = file.stat().st_size / 1024 / 1024
                    if size_mb < 0.1:
                        size_str = f"{file.stat().st_size / 1024:.1f} KB"
                    else:
                        size_str = f"{size_mb:.2f} MB"
                    print(f"  - {file.name} ({size_str})")
        
        if final_zip:
            print(f"\n最终分发包: {final_zip}")
            print(f"用户只需下载此zip包，解压即可使用！")
        
        print("\n分发包内容:")
        print("  1. agent.exe (主程序)")
        print("  2. config.yaml (配置文件，已从example重命名)")
        print("  3. 用户操作指南.docx (使用说明)")
        print("\n使用前请确保:")
        print("  1. 已从 https://platform.deepseek.com 获取API密钥")
        print("  2. 已充值DeepSeek账户")
        print("  3. 将API密钥填入config.yaml")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 打包过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()