"""
Auto-Installer Main Entry Point
Enhanced automated software installation system with history management and logging.
"""

import sys
import argparse
from pathlib import Path

# Add src to path for backward compatibility
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core import AutoInstaller
from config.enhanced_config import EnhancedConfig
from utils.text_processors import TextProcessor

# Global configuration instance
enhanced_config = EnhancedConfig('./config/user_config.json')
def main():
    """Main entry point for the auto-installer."""
    parser = argparse.ArgumentParser(
        description="自动化软件安装助手 - 支持Linux和Mac系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python main.py                          # 交互式安装
  python main.py --install "cmake"        # 直接安装cmake
  python main.py --config config.json    # 使用自定义配置文件
  python main.py --show-config           # 显示当前配置
        """
    )
    
    parser.add_argument(
        '--install', '-i',
        type=str,
        help='要安装的软件名称 (例如: "cmake", "docker", "nodejs")'
    )
    
    parser.add_argument(
        '--config', '-c',
        type=str,
        help='配置文件路径 (JSON格式)'
    )
    
    parser.add_argument(
        '--show-config',
        action='store_true',
        help='显示当前配置信息'
    )
    
    parser.add_argument(
        '--log-dir',
        type=str,
        default='logs',
        help='日志文件目录 (默认: logs)'
    )
    
    parser.add_argument(
        '--max-steps',
        type=int,
        default=30,
        help='最大安装步骤数 (默认: 30)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='显示详细输出'
    )
    
    args = parser.parse_args()
    
    # Load custom config if specified
    if args.config:
        from config.enhanced_config import EnhancedConfig
        global enhanced_config
        enhanced_config = EnhancedConfig(args.config)
    
    # Override config with command line arguments
    if args.log_dir:
        enhanced_config.logging.log_directory = args.log_dir
    
    if args.max_steps:
        enhanced_config.installation.max_installation_steps = args.max_steps
    
    # Show configuration if requested
    if args.show_config:
        enhanced_config.print_config_summary()
        return
    
    # Validate configuration
    validation = enhanced_config.validate_config()
    if validation['errors']:
        print("❌ 配置错误:")
        for error in validation['errors']:
            print(f"  - {error}")
        print("\n请检查配置文件或环境变量设置。")
        sys.exit(1)
    
    if validation['warnings'] and args.verbose:
        print("⚠️ 配置警告:")
        for warning in validation['warnings']:
            print(f"  - {warning}")
        print()
    
    # Get software to install
    if args.install:
        software_request = args.install
    else:
        print("🤖 自动化软件安装助手")
        print("=" * 50)
        print("支持在Linux和Mac系统上自动安装各种软件")
        print("具有智能历史管理和详细日志记录功能")
        print("=" * 50)
        
        software_request = input("\n请输入您需要安装的软件 (可以是中文或英文): ").strip()
        
        if not software_request:
            print("❌ 请提供要安装的软件名称")
            sys.exit(1)
    
    # Initialize installer
    try:
        config_dict = enhanced_config.get_legacy_config_dict()
        installer = AutoInstaller(config_dict)
        
        if args.verbose:
            print(f"\n📋 配置信息:")
            print(f"  - 最大步骤数: {enhanced_config.installation.max_installation_steps}")
            print(f"  - 日志目录: {enhanced_config.logging.log_directory}")
            print(f"  - 历史管理: {'启用' if enhanced_config.history.enable_summarization else '禁用'}")
            print()
        
        # Start installation
        print(f"\n🚀 开始安装: {software_request}")
        success = installer.install_software(software_request)
        
        # Show results
        status = installer.get_installation_status()
        
        print(f"\n{'='*60}")
        print(f"📊 安装结果:")
        print(f"  - 状态: {'✅ 成功' if success else '❌ 失败'}")
        print(f"  - 总步骤数: {status['current_step']}")
        print(f"  - 日志文件: {status['log_file']}")
        print(f"  - 历史记录: {status['history_entries']} 条")
        print(f"{'='*60}")
        
        if success:
            print(f"\n🎉 软件 '{software_request}' 安装完成！")
            print(f"📋 详细安装日志已保存到: {status['log_file']}")
        else:
            print(f"\n💥 软件 '{software_request}' 安装失败")
            print(f"📋 请查看日志文件了解详情: {status['log_file']}")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print(f"\n\n⏹️ 用户中断安装过程")
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ 安装过程中发生错误: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def show_system_info():
    """Display system information."""
    try:
        from utils.get_system_summary import get_system_summary
        
        print("🖥️ 系统信息:")
        print("=" * 50)
        print(get_system_summary())
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ 无法获取系统信息: {e}")


def interactive_config():
    """Interactive configuration setup."""
    print("⚙️ 交互式配置设置")
    print("=" * 30)
    
    # Get API keys
    deepseek_key = input("请输入 Deepseek API Key (必需): ").strip()
    if not deepseek_key:
        print("❌ Deepseek API Key 是必需的")
        return False
    
    kimi_key = input("请输入 Kimi API Key (可选，用于搜索): ").strip()
    
    # Get other settings
    max_steps = input("最大安装步骤数 (默认30): ").strip()
    if not max_steps:
        max_steps = "30"
    
    log_dir = input("日志目录 (默认logs): ").strip()
    if not log_dir:
        log_dir = "logs"
    
    # Update configuration
    enhanced_config.ai_models.deepseek_api_key = deepseek_key
    if kimi_key:
        enhanced_config.ai_models.kimi_api_key = kimi_key
    
    try:
        enhanced_config.installation.max_installation_steps = int(max_steps)
    except ValueError:
        print("⚠️ 无效的步骤数，使用默认值30")
    
    enhanced_config.logging.log_directory = log_dir
    
    # Save configuration
    config_file = "config/user_config.json"
    try:
        enhanced_config.save_to_file(config_file)
        print(f"✅ 配置已保存到: {config_file}")
        return True
    except Exception as e:
        print(f"❌ 保存配置失败: {e}")
        return False


if __name__ == "__main__":
    # Check if this is first run (no API keys configured)
    if not enhanced_config.ai_models.deepseek_api_key:
        print("🔧 首次运行检测到，需要进行配置...")
        
        choice = input("是否进行交互式配置? (y/n): ").strip().lower()
        if choice in ['y', 'yes', '是']:
            if not interactive_config():
                sys.exit(1)
        else:
            print("请设置环境变量或配置文件后再运行。")
            print("环境变量: DEEPSEEK_API_KEY, KIMI_API_KEY")
            sys.exit(1)
    
    main()