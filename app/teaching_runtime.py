"""Executable teaching conditions shared by path planning and resources."""

from importlib.metadata import PackageNotFoundError, version
import sys


def teaching_runtime_context():
    from app.code_sandbox import CODE_SANDBOX_EXECUTOR, SUPPORTED_MODULES
    from config import CONFIG

    installed = {}
    for module, distribution in {"numpy": "numpy", "pandas": "pandas", "matplotlib": "matplotlib",
                                 "sklearn": "scikit-learn", "torch": "torch"}.items():
        try:
            installed[module] = version(distribution)
        except PackageNotFoundError:
            continue
    return {
        "scope": "product_code_sandbox",
        "scopeDescription": "以下网络、文件和依赖限制只约束产品内代码沙盒，不代表学习者的浏览器、外部视频或已确认设备离线。",
        "executionEnabled": CODE_SANDBOX_EXECUTOR.enabled,
        "supportedModules": sorted(SUPPORTED_MODULES),
        "pythonVersion": sys.version.split()[0],
        "installedVersions": installed,
        "compatibilityPolicy": "按实际安装版本编写和核对代码；区分标量、零维数组与非零维数组，明确提取单个元素后再作标量转换。不能仅凭旧版库可运行就断言当前版本可运行。",
        "timeoutSeconds": min(60, max(1, int(CONFIG.sandbox_timeout))),
        "networkAvailable": False,
        "fileAccessAvailable": False,
        "datasetPolicy": (
            "使用正文已明确提供的可内嵌数据，或清楚标为练习数据的可复现合成教学数据。"
            "内存文本/CSV可用io.StringIO，张量或模型参数的保存读回可用io.BytesIO；io只提供这两种内存缓冲区。"
            "不调用fetch_openml、fetch_*或其他联网函数，不假定缓存或本机文件存在。"
            "教材仅给出在线数据集名称或下载代码不等于提供了数据；不得编造真实样本。"
            "保持教材概念正确，但不能把教材中的在线下载步骤设为这里必须完成的条件。"
        ),
        "planningPolicy": (
            "这些条件描述产品内代码环境；用户另有可用工具时，以已确认的设备与工具信息为准。"
            "不要假定已安装教材的d2l、MXNet、TensorFlow或有GPU、联网下载及本地数据。"
            "需要实际训练时，优先安排可内嵌的小数据或清楚标注的合成数据、受支持的框架与合理计算量，"
            "保留训练、验证、误差分析和独立产出；不能用看日志或手算冒充实际训练完成。"
            "课程内环境尚未开启且用户也未确认有其他环境时，明确区分可先完成的理论任务和仍需环境的实践，"
            "不要把等待或只看日志标成实践已完成。编程初学者在首次操作前安排运行、输入修改、输出核对与常见错误准备。"
        ),
    }
