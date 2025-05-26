#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音消息功能测试脚本
用于验证语音消息的编码、解码和数据处理是否正常
"""

import base64
import struct
import os
import sys

# 音频配置（与客户端保持一致）
CHUNK = 1024
FORMAT_SIZE = 2  # pyaudio.paInt16 对应 2 字节
CHANNELS = 1
RATE = 16000

def create_test_audio_data(duration_seconds=2):
    """创建测试音频数据（简单的正弦波）"""
    import math
    
    # 计算样本数
    num_samples = int(RATE * duration_seconds)
    
    # 生成正弦波数据
    frequency = 440  # A4音符
    audio_samples = []
    
    for i in range(num_samples):
        # 生成正弦波样本
        t = i / RATE
        sample = int(16384 * math.sin(2 * math.pi * frequency * t))  # 16位音频的一半幅度
        audio_samples.append(sample)
    
    # 转换为字节数据
    audio_data = struct.pack('<' + 'h' * len(audio_samples), *audio_samples)
    return audio_data

def test_voice_message_encoding():
    """测试语音消息编码"""
    print("=== 测试语音消息编码 ===")
    
    # 创建测试音频数据
    test_audio = create_test_audio_data(2)  # 2秒音频
    print(f"原始音频数据长度: {len(test_audio)} 字节")
    
    # 编码为base64
    try:
        audio_base64 = base64.b64encode(test_audio).decode('utf-8')
        print(f"Base64编码成功，长度: {len(audio_base64)} 字符")
        
        # 检查base64数据中是否包含|字符
        if '|' in audio_base64:
            print("警告: Base64数据中包含|字符，可能会影响消息解析")
        else:
            print("✓ Base64数据中不包含|字符")
        
        return audio_base64, test_audio
    except Exception as e:
        print(f"✗ Base64编码失败: {e}")
        return None, None

def test_voice_message_decoding(audio_base64, original_audio):
    """测试语音消息解码"""
    print("\n=== 测试语音消息解码 ===")
    
    if not audio_base64:
        print("✗ 没有可用的base64数据进行测试")
        return False
    
    try:
        # 修复base64填充问题
        missing_padding = len(audio_base64) % 4
        if missing_padding:
            audio_base64 += '=' * (4 - missing_padding)
            print(f"修复了base64填充，添加了 {4 - missing_padding} 个'='字符")
        
        # 解码
        decoded_audio = base64.b64decode(audio_base64)
        print(f"Base64解码成功，长度: {len(decoded_audio)} 字节")
        
        # 验证数据完整性
        if decoded_audio == original_audio:
            print("✓ 解码数据与原始数据完全一致")
            return True
        else:
            print(f"✗ 解码数据与原始数据不一致")
            print(f"原始长度: {len(original_audio)}, 解码长度: {len(decoded_audio)}")
            return False
            
    except Exception as e:
        print(f"✗ Base64解码失败: {e}")
        return False

def test_message_parsing():
    """测试消息解析"""
    print("\n=== 测试消息解析 ===")
    
    # 创建测试音频数据
    test_audio = create_test_audio_data(1)
    audio_base64 = base64.b64encode(test_audio).decode('utf-8')
    
    # 构造语音消息
    voice_type = "original"
    duration = 1.0
    voice_msg = f'VOICE_MSG|test_user|{voice_type}|{duration}|{audio_base64}'
    
    print(f"构造的语音消息长度: {len(voice_msg)} 字符")
    
    # 测试消息解析（模拟服务端解析）
    try:
        msg_parts = voice_msg.split('|', 4)  # 只分割前4个|
        if len(msg_parts) < 5:
            print(f"✗ 消息解析失败: 参数不足，收到 {len(msg_parts)} 个参数")
            return False
        
        cmd, to_user, parsed_voice_type, parsed_duration, parsed_audio_base64 = msg_parts
        
        print(f"✓ 消息解析成功:")
        print(f"  命令: {cmd}")
        print(f"  目标用户: {to_user}")
        print(f"  语音类型: {parsed_voice_type}")
        print(f"  时长: {parsed_duration}")
        print(f"  音频数据长度: {len(parsed_audio_base64)} 字符")
        
        # 验证解析的数据
        if parsed_audio_base64 == audio_base64:
            print("✓ 音频数据解析正确")
            return True
        else:
            print("✗ 音频数据解析错误")
            return False
            
    except Exception as e:
        print(f"✗ 消息解析失败: {e}")
        return False

def test_audio_data_validation():
    """测试音频数据验证"""
    print("\n=== 测试音频数据验证 ===")
    
    # 创建测试音频数据
    test_audio = create_test_audio_data(1)
    
    # 检查音频数据长度是否为偶数（16位音频每个样本2字节）
    if len(test_audio) % 2 == 0:
        print(f"✓ 音频数据长度为偶数: {len(test_audio)} 字节")
    else:
        print(f"✗ 音频数据长度为奇数: {len(test_audio)} 字节")
        print("  这可能会导致播放问题")
    
    # 检查音频数据是否为空
    if len(test_audio) > 0:
        print("✓ 音频数据不为空")
    else:
        print("✗ 音频数据为空")
        return False
    
    # 检查音频数据格式
    try:
        # 尝试解析为16位整数
        num_samples = len(test_audio) // 2
        samples = struct.unpack('<' + 'h' * num_samples, test_audio)
        print(f"✓ 音频数据格式正确，包含 {num_samples} 个样本")
        
        # 检查样本值范围
        max_sample = max(samples)
        min_sample = min(samples)
        print(f"  样本值范围: {min_sample} 到 {max_sample}")
        
        if -32768 <= min_sample <= 32767 and -32768 <= max_sample <= 32767:
            print("✓ 样本值在16位整数范围内")
            return True
        else:
            print("✗ 样本值超出16位整数范围")
            return False
            
    except Exception as e:
        print(f"✗ 音频数据格式验证失败: {e}")
        return False

def main():
    """主测试函数"""
    print("语音消息功能测试开始\n")
    
    # 测试编码
    audio_base64, original_audio = test_voice_message_encoding()
    
    # 测试解码
    decode_success = test_voice_message_decoding(audio_base64, original_audio)
    
    # 测试消息解析
    parse_success = test_message_parsing()
    
    # 测试音频数据验证
    validation_success = test_audio_data_validation()
    
    # 总结测试结果
    print("\n=== 测试结果总结 ===")
    tests = [
        ("语音消息编码", audio_base64 is not None),
        ("语音消息解码", decode_success),
        ("消息解析", parse_success),
        ("音频数据验证", validation_success)
    ]
    
    passed = 0
    for test_name, result in tests:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\n总计: {passed}/{len(tests)} 个测试通过")
    
    if passed == len(tests):
        print("🎉 所有测试通过！语音消息功能应该可以正常工作。")
        return True
    else:
        print("⚠️  部分测试失败，语音消息功能可能存在问题。")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 