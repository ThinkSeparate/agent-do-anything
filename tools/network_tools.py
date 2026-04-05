# tools/network_tools.py
import os
import requests
from typing import Optional, Dict, Any
from langchain_core.tools import tool
from tools._safety import get_agent_output_root


@tool
def make_http_request(
    url: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    timeout: int = 10
) -> str:
    """发送HTTP请求。"""
    try:
        request_kwargs = {
            'method': method.upper(),
            'url': url,
            'params': params,
            'headers': headers,
            'timeout': timeout
        }
        if json_data is not None:
            request_kwargs['json'] = json_data
        elif data is not None:
            request_kwargs['data'] = data

        response = requests.request(**request_kwargs)
        response.raise_for_status()

        try:
            response_content = response.json()
        except requests.exceptions.JSONDecodeError:
            response_content = response.text

        return str({
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'content': response_content,
            'url': response.url
        })

    except requests.exceptions.Timeout:
        return f"网络请求超时（{timeout}秒）。"
    except requests.exceptions.HTTPError as e:
        return f"HTTP请求失败，状态码：{e.response.status_code}。"
    except requests.exceptions.ConnectionError:
        return f"网络连接错误，请检查URL '{url}' 或网络状态。"
    except requests.exceptions.RequestException as e:
        return f"网络请求发生异常: {e}"
    except Exception as e:
        return f"执行网络请求工具时发生未知错误: {e}"


@tool
def download_file(url: str, local_path: str) -> str:
    """从指定的URL下载文件到本地路径。"""
    # 安全检查
    agent_output_root = get_agent_output_root()
    if agent_output_root is not None:
        try:
            target_abs_path = os.path.abspath(local_path)
            agent_output_root_abs = os.path.abspath(agent_output_root)
        except Exception:
            target_abs_path = local_path
            agent_output_root_abs = agent_output_root

        is_safe_path = False
        try:
            common_path = os.path.commonpath([agent_output_root_abs, target_abs_path])
            is_safe_path = os.path.commonpath([agent_output_root_abs]) == common_path
        except (ValueError, TypeError):
            is_safe_path = False

        if not is_safe_path:
            should_continue = input(f"\n⚠️  即将下载文件到: {target_abs_path}\n是否继续？（Y/N）: ")
            if should_continue.lower() != 'y':
                return "用户取消了文件下载操作。"

    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

        if total_size and os.path.getsize(local_path) != total_size:
            return f"警告：下载文件大小 ({os.path.getsize(local_path)} 字节) 与预期大小 ({total_size} 字节) 不匹配。文件可能不完整。"

        return f"文件已成功下载到 '{local_path}' (大小: {os.path.getsize(local_path)} 字节)。"

    except requests.exceptions.RequestException as e:
        return f"下载文件时发生网络错误: {e}"
    except OSError as e:
        return f"写入本地文件时发生错误: {e}"
    except Exception as e:
        return f"下载文件时发生未知错误: {e}"


network_tools = [make_http_request, download_file]
