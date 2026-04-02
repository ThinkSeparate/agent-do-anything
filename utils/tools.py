# utils/tools.py
import os
import subprocess
from docx import Document
from pptx import Presentation
from pptx.util import Inches

# --- 修改：定义一个安全的、可动态获取根路径的调用器 ---
# 默认情况下，此调用器返回 None，表示不进行安全检查。
_GET_AGENT_OUTPUT_ROOT = lambda: None

def configure_agent_output_root(getter_func):
    """
    配置安全写入目录（agent_output）根路径的获取方式。
    此函数应由系统初始化流程（如ReActAgent）调用。
    
    Args:
        getter_func: 一个可调用对象，在需要时返回 agent_output 目录的绝对路径字符串。
                     如果返回 None，则跳过安全检查。
    """
    global _GET_AGENT_OUTPUT_ROOT
    _GET_AGENT_OUTPUT_ROOT = getter_func
# --- 修改结束 ---

class ToolSet:
    @staticmethod
    def create_ppt(file_path: str, title: str = "Presentation") -> dict:
        """创建一个新的PPT文件，并添加一个标题幻灯片。"""
        try:
            prs = Presentation()
            # 使用标题幻灯片布局
            slide_layout = prs.slide_layouts[0]
            slide = prs.slides.add_slide(slide_layout)
            title_shape = slide.shapes.title
            title_shape.text = title
            prs.save(file_path)
            return {'operation_succeeded': True, 'data': f"PPT文件已创建于 '{file_path}'，标题为 '{title}'。"}
        except Exception as e:
            return {'operation_succeeded': False, 'data': f"创建PPT文件时出错: {e}"}

    @staticmethod
    def add_slide_to_ppt(file_path: str, title: str = "", content: str = "") -> dict:
        """向现有PPT文件添加一个幻灯片。"""
        try:
            prs = Presentation(file_path)
            # 使用标题和内容布局（通常是第1个布局）
            slide_layout = prs.slide_layouts[1]
            slide = prs.slides.add_slide(slide_layout)
            title_shape = slide.shapes.title
            title_shape.text = title
            content_shape = slide.placeholders[1]  # 通常是内容占位符
            content_shape.text = content
            prs.save(file_path)
            return {'operation_succeeded': True, 'data': f"已向PPT文件添加幻灯片，标题: '{title}'。"}
        except FileNotFoundError:
            return {'operation_succeeded': False, 'data': f"错误：找不到文件 '{file_path}'。"}
        except Exception as e:
            return {'operation_succeeded': False, 'data': f"添加幻灯片时出错: {e}"}

    @staticmethod
    def read_ppt(file_path: str) -> dict:
        """读取PPT文件并返回幻灯片标题和内容的文本表示。"""
        try:
            prs = Presentation(file_path)
            slides_data = []
            for i, slide in enumerate(prs.slides):
                title = slide.shapes.title.text if slide.shapes.title else ""
                content = ""
                # 收集所有文本框内容（除了标题）
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape != slide.shapes.title:
                        content += shape.text + "\n"
                slides_data.append(f"幻灯片 {i}: 标题='{title}', 内容='{content.strip()}'")
            return {'operation_succeeded': True, 'data': "\n".join(slides_data)}
        except FileNotFoundError:
            return {'operation_succeeded': False, 'data': f"错误：找不到文件 '{file_path}'。"}
        except Exception as e:
            return {'operation_succeeded': False, 'data': f"读取PPT文件时出错: {e}"}

    @staticmethod
    def modify_ppt_slide(file_path: str, slide_index: int, new_title: str = None, new_content: str = None) -> dict:
        """修改指定索引的幻灯片。"""
        try:
            prs = Presentation(file_path)
            if 0 <= slide_index < len(prs.slides):
                slide = prs.slides[slide_index]
                if new_title is not None and slide.shapes.title:
                    slide.shapes.title.text = new_title
                if new_content is not None:
                    # 这里简单假设内容在第一个非标题的文本框中
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape != slide.shapes.title:
                            shape.text = new_content
                            break
                prs.save(file_path)
                return {'operation_succeeded': True, 'data': f"已成功更新第 {slide_index} 张幻灯片。"}
            else:
                return {'operation_succeeded': False, 'data': f"错误：幻灯片索引 {slide_index} 超出范围。"}
        except FileNotFoundError:
            return {'operation_succeeded': False, 'data': f"错误：找不到文件 '{file_path}'。"}
        except Exception as e:
            return {'operation_succeeded': False, 'data': f"修改幻灯片时出错: {e}"}
    
    @staticmethod
    def read_docx(file_path: str) -> str:
        """读取 DOCX 文件并返回其纯文本内容。"""
        doc = Document(file_path)
        full_text = []
        for paragraph in doc.paragraphs:
            full_text.append(paragraph.text)
        return {'operation_succeeded': True, 'data': "\n".join(full_text)}

    @staticmethod
    def modify_docx_paragraph(file_path: str, paragraph_index: int, new_text: str) -> str:
        """修改 DOCX 文件中指定段落的文本。"""
        doc = Document(file_path)
        if 0 <= paragraph_index < len(doc.paragraphs):
            doc.paragraphs[paragraph_index].text = new_text
            doc.save(file_path)
            return {'operation_succeeded': True, 'data': f"已成功更新第 {paragraph_index} 段内容。"}
        else:
            return {'operation_succeeded': False, 'data': f"错误：段落索引 {paragraph_index} 超出范围。"}
    
    @staticmethod
    def read_file(file_path):
        """用于读取文件内容"""
        try:
            normalized_path = os.path.normpath(file_path)
            with open(normalized_path, "r", encoding="utf-8") as f:
                content = f.read()
            # 操作成功，将内容放入 'data'
            return {'operation_succeeded': True, 'data': content}
        except FileNotFoundError:
            # 操作失败，将错误信息放入 'data'，也可明确设置 'error'
            return {'operation_succeeded': False, 'data': f"错误：找不到文件 '{normalized_path}'。"}
        except OSError as e:
            return {'operation_succeeded': False, 'data': f"错误：无法读取文件 '{normalized_path}'。系统报告: {e}"}
        except Exception as e:
            return {'operation_succeeded': False, 'data': f"读取文件时发生未知错误: {e}"}

    @staticmethod
    def write_to_file(file_path, content):
        """将指定内容写入指定文件"""
        # 1. 动态获取安全目录根路径
        agent_output_root = _GET_AGENT_OUTPUT_ROOT()
        
        # 2. 仅在 getter 返回有效路径时进行检查
        if agent_output_root is not None:
            try:
                target_abs_path = os.path.abspath(file_path)
                agent_output_root_abs = os.path.abspath(agent_output_root)
            except Exception:
                # 路径解析异常，视为不安全
                target_abs_path = file_path
                agent_output_root_abs = agent_output_root
            
            is_safe_path = False
            try:
                common_path = os.path.commonpath([agent_output_root_abs, target_abs_path])
                is_safe_path = os.path.commonpath([agent_output_root_abs]) == common_path
            except (ValueError, TypeError):
                is_safe_path = False
            
            # 如果路径不安全，需要用户确认
            if not is_safe_path:
                should_continue = input(f"\n⚠️  即将向: {target_abs_path} 目录写入文件\n是否继续？（Y/N）: ")
                if should_continue.lower() != 'y':
                    return {'operation_succeeded': False, 'data': "用户取消了文件写入操作。"}
        
        # 以下是原有的写入逻辑
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content.replace("\\n", "\n"))
            return {'operation_succeeded': True, 'data': f"文件 '{file_path}' 写入成功。"}
        except Exception as e:
            return {'operation_succeeded': False, 'data': f"写入文件 '{file_path}' 时发生错误: {e}"}
    
    @staticmethod
    def run_terminal_command(command):
        """用于执行终端命令"""
        should_continue = input(f"\n⚠️  即将执行终端命令: {command}\n是否继续？（Y/N）: ")
        if should_continue.lower() != 'y':
            # 用户取消，也是一种操作失败
            return {'operation_succeeded': False, 'data': "用户取消了终端命令的执行。"}
        
        run_result = subprocess.run(command, shell=True, capture_output=True, text=True)
        
        if run_result.returncode == 0:
            output = run_result.stdout.strip()
            result_data = f"命令执行成功。输出：\n{output}" if output else "命令执行成功（无输出）。"
            return {
                'operation_succeeded': True,
                'data': result_data,
                'returncode': run_result.returncode
            }
        else:
            error_output = run_result.stderr.strip()
            return {
                'operation_succeeded': False,
                'data': f"命令执行失败（返回码 {run_result.returncode}）。错误输出：\n{error_output}",
                'returncode': run_result.returncode
            }