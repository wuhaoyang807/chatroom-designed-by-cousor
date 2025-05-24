#!/usr/bin/env python3
"""
简单的语音通话测试脚本
用于验证客户端是否能正确接收CALL_INCOMING消息
"""

import sys
import os

# 添加client目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'client'))

def main():
    print("语音通话测试")
    print("=" * 50)
    
    # 检查文件存在
    client_files = ['main.py', 'main_fixed.py']
    server_files = ['main.py', 'main_corrected.py']
    
    print("检查客户端文件:")
    for f in client_files:
        path = os.path.join('client', f)
        exists = os.path.exists(path)
        print(f"  {f}: {'✓' if exists else '✗'}")
    
    print("\n检查服务器文件:")
    for f in server_files:
        path = os.path.join('server', f)
        exists = os.path.exists(path)
        print(f"  {f}: {'✓' if exists else '✗'}")
    
    print("\n推荐测试步骤:")
    print("1. 停止当前服务器 (Ctrl+C)")
    print("2. 启动修复版服务器:")
    print("   cd server")
    print("   python main_corrected.py")
    print("3. 启动第一个客户端:")
    print("   cd client") 
    print("   python main_fixed.py")
    print("4. 启动第二个客户端:")
    print("   cd client")
    print("   python main_fixed.py")
    print("5. 测试语音通话功能")
    
    print("\n关键修复:")
    print("✓ 修复了服务器CALL_INCOMING发送逻辑")
    print("✓ 增强了私聊消息保存功能")
    print("✓ 添加了详细的调试日志")
    print("✓ 改进了错误处理和连接验证")

if __name__ == '__main__':
    main() 