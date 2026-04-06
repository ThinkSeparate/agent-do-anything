# 检查工具属性

from tools.network_tools import make_http_request

tool = make_http_request
print(f"工具名称: {tool.name}")  # 应为'make_http_request'
print(f"工具描述: {tool.description}")  # 应显示docstring
print(f"参数schema: {tool.args}")  # 应显示参数定义

# 测试调用
# result = tool.invoke({
#     "url": "https://httpbin.org/get",
#     "method": "GET"
# })
# print(f"调用结果: {result}")