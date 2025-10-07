import platform
import psutil
import GPUtil
import shutil

def detect_package_manager():
    # 检查 apt 是否存在
    if shutil.which("apt"):
        return "系统支持 apt 包管理器 (Debian/Ubuntu)"
    # 检查 yum 是否存在
    elif shutil.which("yum"):
        return "系统支持 yum 包管理器 (RHEL/CentOS)"
    # 检查 dnf 是否存在
    elif shutil.which("dnf"):
        return "系统支持 dnf 包管理器 (Fedora/RHEL)"
    # 检查 pacman 是否存在
    elif shutil.which("pacman"):
        return "系统支持 pacman 包管理器 (Arch Linux)"
    else:
        return "无法检测到支持的包管理器"

def check_python_tools():
    tools = {
        "conda": "Conda 包管理器",
        "uv": "UV Python 管理工具"
    }
    
    installed_tools = []
    
    for tool, description in tools.items():
        if shutil.which(tool):
            installed_tools.append(description)
    
    if not installed_tools:
        return "系统未安装 Conda 或 UV Python 管理工具"
    
    return f"系统已安装: {', '.join(installed_tools)}"

def check_sudo_support():
    # 检查 sudo 命令是否存在于系统路径中
    if shutil.which("sudo"):
        return "系统支持 sudo 命令"
    else:
        return "系统不支持 sudo 命令"

def get_system_summary():
    # 获取操作系统相关信息
    os_info = platform.uname()
    os_summary = f"操作系统: {os_info.system}\n节点名称: {os_info.node}\n操作系统版本: {os_info.release}\n操作系统版本号: {os_info.version}\n机器类型: {os_info.machine}"
    
    # 检查GPU信息
    gpus = GPUtil.getGPUs()
    if gpus:
        gpu_summary = "检测到GPU:\n"
        for gpu in gpus:
            gpu_summary += f"GPU型号: {gpu.name}\n内存大小: {gpu.memoryTotal} MB\n"
    else:
        gpu_summary = "没有检测到GPU。"

    # 获取CPU信息
    cpu_summary = f"CPU型号: {platform.processor()}\nCPU核数: {psutil.cpu_count(logical=False)} 物理核, {psutil.cpu_count(logical=True)} 逻辑核"

    # 获取内存信息
    virtual_memory = psutil.virtual_memory()
    memory_summary = f"内存大小: {virtual_memory.total / (1024 ** 3):.2f} GB"

    manager = detect_package_manager()
    python_manager = check_python_tools()
    sudo_support = check_sudo_support()
    # 生成总结字符串
    summary = f"{os_summary}\n{gpu_summary}\n{cpu_summary}\n{memory_summary}\n{manager}\n{python_manager}\n{sudo_support}"
    return summary

if __name__ == "__main__":
    summary = get_system_summary()
    print(summary)
