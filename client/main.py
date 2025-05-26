import sys
import socket
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
                             QListWidget, QMessageBox, QInputDialog, QListWidgetItem, QTabWidget, QDialog,
                             QDesktopWidget, QFileDialog, QProgressDialog, QGraphicsOpacityEffect, QComboBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QByteArray
from PyQt5.QtGui import QIcon, QPixmap, QMovie, QColor
import os
import pyaudio
import wave
import time
import struct
import logging
import datetime
import random  # 添加随机数模块用于端口分配
import shutil
import tkinter.filedialog
import tkinter.messagebox
import json
import threading
import tkinter.messagebox
import os
import hashlib
import audioop  # 添加音频操作模块

# 配置日志
log_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f'client_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# 音频压缩工具类
class AudioCompressor:
    """简单的音频压缩工具，用于减少网络传输数据量"""
    
    @staticmethod
    def compress_audio(audio_data, compression_level=2):
        """
        压缩音频数据
        compression_level: 1-4，数字越大压缩率越高但质量越低
        """
        try:
            if not audio_data or len(audio_data) == 0:
                return audio_data
            
            # 根据压缩级别调整采样
            if compression_level == 1:
                # 轻度压缩：保持原始质量
                return audio_data
            elif compression_level == 2:
                # 中度压缩：降低音量动态范围，并添加简单的回声抑制
                # 降低音量以减少反馈
                reduced_volume = audioop.mul(audio_data, 2, 0.6)  # 降低音量到60%
                return reduced_volume
            elif compression_level == 3:
                # 高度压缩：降低位深度
                # 将16位音频转换为8位再转回16位
                audio_8bit = audioop.lin2lin(audio_data, 2, 1)
                return audioop.lin2lin(audio_8bit, 1, 2)
            elif compression_level == 4:
                # 最高压缩：降低采样率
                # 模拟降低采样率（每隔一个样本取一个）
                samples = struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data)
                compressed_samples = samples[::2]  # 取每隔一个样本
                # 重复样本以恢复原始长度
                restored_samples = []
                for sample in compressed_samples:
                    restored_samples.extend([sample, sample])
                # 截断到原始长度
                restored_samples = restored_samples[:len(samples)]
                return struct.pack('<' + 'h' * len(restored_samples), *restored_samples)
            else:
                return audio_data
        except Exception as e:
            logging.error(f"音频压缩失败: {e}")
            return audio_data
    
    @staticmethod
    def decompress_audio(audio_data, compression_level=2):
        """
        解压缩音频数据（目前主要是音量调整）
        """
        try:
            if not audio_data or len(audio_data) == 0:
                return audio_data
            
            # 对于大多数压缩级别，解压缩就是恢复音量
            if compression_level == 2:
                # 恢复音量，但保持在合理范围内以避免反馈
                return audioop.mul(audio_data, 2, 1.1)  # 恢复音量到110%
            else:
                return audio_data
        except Exception as e:
            logging.error(f"音频解压缩失败: {e}")
            return audio_data

    @staticmethod
    def apply_echo_suppression(audio_data):
        """
        简单的回声抑制：检测音频强度，如果太高则降低音量
        """
        try:
            if not audio_data or len(audio_data) == 0:
                return audio_data
            
            # 计算音频的RMS（均方根）值来判断音量
            rms = audioop.rms(audio_data, 2)
            
            # 如果音量过高（可能是反馈），则大幅降低音量
            if rms > 8000:  # 阈值可以调整
                return audioop.mul(audio_data, 2, 0.3)  # 降低到30%
            elif rms > 5000:
                return audioop.mul(audio_data, 2, 0.6)  # 降低到60%
            else:
                return audio_data
        except Exception as e:
            logging.error(f"回声抑制失败: {e}")
            return audio_data


# 变音工具类
class VoiceChanger:
    """语音变音工具类"""
    
    @staticmethod
    def change_pitch(audio_data, pitch_factor):
        """
        改变音调
        pitch_factor: 音调变化因子，>1提高音调，<1降低音调
        """
        try:
            if not audio_data or len(audio_data) == 0:
                logging.warning("变音处理: 音频数据为空")
                return audio_data
            
            # 确保音频数据长度为偶数
            if len(audio_data) % 2 != 0:
                audio_data = audio_data[:-1]
                logging.warning("变音处理: 调整音频数据长度为偶数")
            
            # 如果调整后数据为空，返回原始数据
            if len(audio_data) == 0:
                logging.warning("变音处理: 调整后音频数据为空")
                return audio_data
            
            # 将字节数据转换为样本数组
            num_samples = len(audio_data) // 2
            if num_samples == 0:
                logging.warning("变音处理: 样本数为0")
                return audio_data
                
            samples = struct.unpack('<' + 'h' * num_samples, audio_data)
            logging.debug(f"变音处理: 原始样本数={num_samples}, pitch_factor={pitch_factor}")
            
            # 简单的音调变化：通过改变采样率来实现
            if abs(pitch_factor - 1.0) > 0.01:  # 只有当变化明显时才处理
                # 重新采样以改变音调
                new_length = max(1, int(len(samples) / pitch_factor))  # 确保至少有1个样本
                new_samples = []
                
                for i in range(new_length):
                    # 线性插值
                    old_index = i * pitch_factor
                    index1 = int(old_index)
                    index2 = min(index1 + 1, len(samples) - 1)
                    
                    if index1 < len(samples):
                        # 线性插值计算新样本值
                        fraction = old_index - index1
                        sample = samples[index1] * (1 - fraction) + samples[index2] * fraction
                        # 确保样本值在有效范围内
                        sample = max(-32768, min(32767, int(sample)))
                        new_samples.append(sample)
                
                # 确保有足够的样本
                if len(new_samples) == 0:
                    logging.warning("变音处理: 新样本数为0，返回原始数据")
                    return audio_data
                
                # 如果新长度小于原长度，需要填充或截断到原长度
                if len(new_samples) < len(samples):
                    # 重复最后的样本来填充
                    last_sample = new_samples[-1] if new_samples else 0
                    while len(new_samples) < len(samples):
                        new_samples.append(last_sample)
                else:
                    # 截断到原长度
                    new_samples = new_samples[:len(samples)]
                
                logging.debug(f"变音处理: 新样本数={len(new_samples)}")
                
                # 验证样本数据
                if len(new_samples) == 0:
                    logging.warning("变音处理: 最终样本数为0，返回原始数据")
                    return audio_data
                
                # 转换回字节数据
                try:
                    result = struct.pack('<' + 'h' * len(new_samples), *new_samples)
                    logging.debug(f"变音处理: 输出数据长度={len(result)}")
                    
                    # 验证输出数据
                    if len(result) == 0:
                        logging.warning("变音处理: 输出数据长度为0，返回原始数据")
                        return audio_data
                    
                    return result
                except struct.error as pack_error:
                    logging.error(f"变音处理: 数据打包失败: {pack_error}")
                    return audio_data
            else:
                logging.debug("变音处理: pitch_factor接近1.0，返回原始数据")
                return audio_data
                
        except Exception as e:
            logging.error(f"变音处理失败: {e}")
            import traceback
            traceback.print_exc()
            return audio_data
    
    @staticmethod
    def apply_female_voice(audio_data):
        """
        应用女声效果（提高音调）
        """
        try:
            result = VoiceChanger.change_pitch(audio_data, 1.3)  # 提高30%的音调
            logging.debug(f"女声变音处理: 输入长度={len(audio_data)}, 输出长度={len(result)}")
            return result
        except Exception as e:
            logging.error(f"女声变音处理失败: {e}")
            return audio_data  # 如果变音失败，返回原始音频
    
    @staticmethod
    def apply_original_voice(audio_data):
        """
        保持原声
        """
        return audio_data

# 服务器配置
SERVER_HOST = '127.0.0.1'  # 默认本地地址why
SERVER_PORT = 12345
UDP_PORT_BASE = 40000  # 本地UDP端口基址

EMOJI_DIR = os.path.join(os.path.dirname(__file__), 'resources')
# 在EMOJI_DIR定义附近添加背景图片文件夹
BG_DIR = os.path.join(os.path.dirname(__file__), 'backgrounds')
os.makedirs(BG_DIR, exist_ok=True)

# 添加文件存储目录
FILES_DIR = os.path.join(os.path.dirname(__file__), 'files')
os.makedirs(FILES_DIR, exist_ok=True)

# 音频配置
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000


# 添加一个全局函数来确保窗口显示在屏幕中央
def center_window(window):
    """将窗口定位到屏幕中央"""
    screen = QDesktopWidget().screenGeometry()
    size = window.geometry()
    window.move((screen.width() - size.width()) // 2,
                (screen.height() - size.height()) // 2)


def check_network_config():
    """检查网络配置"""
    try:
        # 尝试解析服务器地址
        socket.gethostbyname(SERVER_HOST)
        logging.debug(f"服务器地址 {SERVER_HOST} 解析成功")

        # 测试服务器连接
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(5)  # 设置5秒超时
        test_sock.connect((SERVER_HOST, SERVER_PORT))
        test_sock.close()
        logging.debug(f"成功连接到服务器 {SERVER_HOST}:{SERVER_PORT}")

        return True
    except socket.gaierror:
        logging.error(f"无法解析服务器地址: {SERVER_HOST}")
        QMessageBox.critical(None, '网络错误', f'无法解析服务器地址: {SERVER_HOST}\n请确保服务器地址正确')
        return False
    except socket.timeout:
        logging.error(f"连接服务器超时: {SERVER_HOST}:{SERVER_PORT}")
        QMessageBox.critical(None, '网络错误', f'连接服务器超时\n请确保服务器正在运行且网络连接正常')
        return False
    except ConnectionRefusedError:
        logging.error(f"服务器拒绝连接: {SERVER_HOST}:{SERVER_PORT}")
        QMessageBox.critical(None, '网络错误', f'服务器拒绝连接\n请确保服务器正在运行且端口 {SERVER_PORT} 已开放')
        return False
    except Exception as e:
        logging.error(f"网络配置检查失败: {e}")
        QMessageBox.critical(None, '网络错误', f'网络配置检查失败: {e}')
        return False


class ClientThread(QThread):
    message_received = pyqtSignal(str)
    connection_lost = pyqtSignal()

    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self.running = True
        self.buffer = b''  # 用于存储部分接收的消息
        logging.debug("客户端线程初始化")

    def run(self):
        logging.debug("客户端线程开始运行")
        self.sock.settimeout(1.0)  # 设置1秒超时，使循环可以被中断

        while self.running:
            try:
                try:
                    data = self.sock.recv(16384)
                    if not data:
                        logging.warning("服务器连接断开")
                        self.connection_lost.emit()
                        break
                    self.buffer += data
                    while b'\n' in self.buffer:
                        line, self.buffer = self.buffer.split(b'\n', 1)
                        try:
                            msg = line.decode('utf-8')
                            self.message_received.emit(msg)
                        except UnicodeDecodeError:
                            continue
                except socket.timeout:
                    continue
            except ConnectionResetError:
                logging.error("连接被重置")
                self.connection_lost.emit()
                break
            except Exception as e:
                logging.error(f"接收消息出错: {e}")
                self.connection_lost.emit()
                break
        logging.debug("客户端线程结束")

    def stop(self):
        logging.debug("停止客户端线程")
        self.running = False
        self.quit()
        self.wait()


class UDPAudioThread(QThread):
    """处理UDP音频数据接收的线程"""
    audio_received = pyqtSignal(bytes)

    def __init__(self, local_port):
        super().__init__()
        self.local_port = local_port
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind(('0.0.0.0', self.local_port))
        self.udp_socket.settimeout(0.5)  # 设置超时以便于停止线程
        self.running = True
        self.error_occurred = False
        logging.debug(f"UDP音频线程绑定到端口: {self.local_port}")

    def run(self):
        while self.running and not self.error_occurred:
            try:
                data, addr = self.udp_socket.recvfrom(65536)
                if data and len(data) > 1:
                    try:
                        # 解析头部
                        header_len = data[0]
                        if len(data) > header_len + 1:
                            # 提取音频数据（跳过头部）
                            audio_data = data[header_len + 1:]
                            if audio_data and len(audio_data) > 0:
                                logging.debug(f"收到UDP音频数据: {len(audio_data)} 字节，来自: {addr}")
                                self.audio_received.emit(audio_data)
                    except Exception as e:
                        logging.error(f"处理UDP数据包错误: {e}")
                        self.error_occurred = True
            except socket.timeout:
                continue
            except Exception as e:
                logging.error(f"UDP接收错误: {e}")
                self.error_occurred = True
                time.sleep(0.1)

    def send_audio(self, audio_data, target_addr, sender, receiver):
        try:
            if not audio_data or not target_addr or len(audio_data) == 0:
                logging.warning("无效的音频数据或目标地址")
                return

            # 验证目标地址格式
            if not isinstance(target_addr, tuple) or len(target_addr) != 2:
                logging.warning(f"无效的目标地址格式: {target_addr}")
                return

            # 验证IP地址和端口
            try:
                ip, port = target_addr
                if not ip or port <= 0 or port > 65535:
                    logging.warning(f"无效的IP或端口: {ip}:{port}")
                    return
            except (ValueError, TypeError):
                logging.warning(f"目标地址解析失败: {target_addr}")
                return

            # 创建头部：发送者|接收者
            header = f"{sender}|{receiver}"
            header_bytes = header.encode('utf-8')
            header_len = len(header_bytes)

            # 创建完整的数据包：头部长度(1字节) + 头部 + 音频数据
            packet = bytearray([header_len]) + header_bytes + audio_data

            # 发送数据，增加重试机制
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.udp_socket.sendto(packet, target_addr)
                    # 每发送50个包记录一次日志
                    if hasattr(self, 'send_count'):
                        self.send_count += 1
                    else:
                        self.send_count = 1
                    
                    if self.send_count % 50 == 0:
                        logging.debug(f"发送UDP音频数据: 包 #{self.send_count}, {len(audio_data)} 字节，到: {target_addr}")
                    break  # 发送成功，退出重试循环
                except Exception as send_error:
                    if attempt < max_retries - 1:
                        logging.warning(f"UDP发送失败，重试 {attempt + 1}/{max_retries}: {send_error}")
                        time.sleep(0.001)  # 短暂延迟后重试
                    else:
                        raise send_error  # 最后一次重试失败，抛出异常

        except Exception as e:
            logging.error(f"UDP发送错误: {e}")
            self.error_occurred = True

    def stop(self):
        self.running = False
        self.quit()
        self.wait()
        try:
            self.udp_socket.close()
        except Exception as e:
            print(f"关闭UDP socket错误: {e}")


class VoiceMessageDialog(QDialog):
    """语音消息录制对话框"""
    voice_message_ready = pyqtSignal(bytes, str)  # 音频数据和变音类型

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("录制语音消息")
        self.setFixedSize(350, 250)
        self.setModal(True)
        
        self.audio = None
        self.stream = None
        self.recording = False
        self.audio_data = []
        self.voice_type = "original"  # 默认原声
        
        self.init_ui()
        center_window(self)

    def init_ui(self):
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("🎤 录制语音消息")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #2E86AB;")
        
        # 变音选择
        voice_group = QVBoxLayout()
        voice_label = QLabel("选择声音类型:")
        voice_label.setStyleSheet("font-weight: bold;")
        
        self.voice_radio_layout = QHBoxLayout()
        self.original_radio = QPushButton("原声")
        self.female_radio = QPushButton("女声")
        
        # 设置按钮样式
        button_style = """
            QPushButton {
                background-color: #f0f0f0;
                border: 2px solid #ccc;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:checked {
                background-color: #2E86AB;
                color: white;
                border-color: #2E86AB;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:checked:hover {
                background-color: #1E5F7A;
            }
        """
        
        self.original_radio.setCheckable(True)
        self.female_radio.setCheckable(True)
        self.original_radio.setChecked(True)  # 默认选中原声
        self.original_radio.setStyleSheet(button_style)
        self.female_radio.setStyleSheet(button_style)
        
        # 设置互斥选择
        self.original_radio.clicked.connect(lambda: self.select_voice_type("original"))
        self.female_radio.clicked.connect(lambda: self.select_voice_type("female"))
        
        self.voice_radio_layout.addWidget(self.original_radio)
        self.voice_radio_layout.addWidget(self.female_radio)
        
        voice_group.addWidget(voice_label)
        voice_group.addLayout(self.voice_radio_layout)
        
        # 录制状态显示
        self.status_label = QLabel("点击开始录制")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #666; font-size: 12pt;")
        
        # 录制时长显示
        self.duration_label = QLabel("录制时长: 00:00")
        self.duration_label.setAlignment(Qt.AlignCenter)
        self.duration_label.setStyleSheet("color: #666; font-size: 10pt;")
        
        # 录制按钮
        self.record_btn = QPushButton("🎤 开始录制")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 14pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:pressed {
                background-color: #1e7e34;
            }
        """)
        self.record_btn.clicked.connect(self.toggle_recording)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        self.send_btn = QPushButton("发送")
        self.cancel_btn = QPushButton("取消")
        
        self.send_btn.setEnabled(False)  # 初始禁用
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover:enabled {
                background-color: #0056b3;
            }
            QPushButton:disabled {
                background-color: #ccc;
                color: #666;
            }
        """)
        
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #545b62;
            }
        """)
        
        self.send_btn.clicked.connect(self.send_voice_message)
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(self.send_btn)
        button_layout.addWidget(self.cancel_btn)
        
        # 组装布局
        layout.addWidget(title_label)
        layout.addSpacing(10)
        layout.addLayout(voice_group)
        layout.addSpacing(10)
        layout.addWidget(self.status_label)
        layout.addWidget(self.duration_label)
        layout.addSpacing(10)
        layout.addWidget(self.record_btn)
        layout.addSpacing(10)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # 录制计时器
        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self.update_duration)
        self.record_start_time = 0

    def select_voice_type(self, voice_type):
        """选择变音类型"""
        self.voice_type = voice_type
        if voice_type == "original":
            self.original_radio.setChecked(True)
            self.female_radio.setChecked(False)
        else:
            self.original_radio.setChecked(False)
            self.female_radio.setChecked(True)

    def toggle_recording(self):
        """切换录制状态"""
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        """开始录制"""
        try:
            self.audio = pyaudio.PyAudio()
            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK
            )
            
            self.recording = True
            self.audio_data = []
            self.record_start_time = time.time()
            
            # 更新UI
            self.record_btn.setText("⏹ 停止录制")
            self.record_btn.setStyleSheet("""
                QPushButton {
                    background-color: #dc3545;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 12px;
                    font-size: 14pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #c82333;
                }
            """)
            self.status_label.setText("🔴 正在录制...")
            self.status_label.setStyleSheet("color: red; font-size: 12pt; font-weight: bold;")
            
            # 禁用变音选择
            self.original_radio.setEnabled(False)
            self.female_radio.setEnabled(False)
            
            # 开始计时器
            self.record_timer.start(100)  # 每100ms更新一次
            
            # 开始录制线程
            self.record_thread = threading.Thread(target=self.record_audio)
            self.record_thread.daemon = True
            self.record_thread.start()
            
        except Exception as e:
            QMessageBox.warning(self, "录制错误", f"无法开始录制: {e}")
            self.recording = False

    def record_audio(self):
        """录制音频数据"""
        try:
            while self.recording and self.stream:
                try:
                    data = self.stream.read(CHUNK, exception_on_overflow=False)
                    if data and len(data) > 0:
                        self.audio_data.append(data)
                    else:
                        logging.warning("录制到空音频数据")
                except Exception as read_error:
                    logging.error(f"读取音频数据失败: {read_error}")
                    break
        except Exception as e:
            logging.error(f"录制音频出错: {e}")
            self.recording = False

    def stop_recording(self):
        """停止录制"""
        self.recording = False
        self.record_timer.stop()
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        if self.audio:
            self.audio.terminate()
            self.audio = None
        
        # 更新UI
        self.record_btn.setText("🎤 重新录制")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 14pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        
        if self.audio_data:
            duration = time.time() - self.record_start_time
            self.status_label.setText(f"✅ 录制完成 ({duration:.1f}秒)")
            self.status_label.setStyleSheet("color: green; font-size: 12pt; font-weight: bold;")
            self.send_btn.setEnabled(True)
        else:
            self.status_label.setText("录制失败，请重试")
            self.status_label.setStyleSheet("color: red; font-size: 12pt;")
        
        # 重新启用变音选择
        self.original_radio.setEnabled(True)
        self.female_radio.setEnabled(True)

    def update_duration(self):
        """更新录制时长显示"""
        if self.recording:
            duration = time.time() - self.record_start_time
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            self.duration_label.setText(f"录制时长: {minutes:02d}:{seconds:02d}")

    def send_voice_message(self):
        """发送语音消息"""
        if not self.audio_data:
            QMessageBox.warning(self, "提示", "请先录制语音消息")
            return
        
        try:
            # 合并音频数据
            audio_bytes = b''.join(self.audio_data)
            logging.debug(f"合并音频数据: 原始长度={len(audio_bytes)}")
            
            # 验证音频数据
            if len(audio_bytes) == 0:
                QMessageBox.warning(self, "错误", "录制的音频数据为空")
                return
            
            # 应用变音效果
            if self.voice_type == "female":
                logging.debug("应用女声变音效果")
                audio_bytes = VoiceChanger.apply_female_voice(audio_bytes)
                logging.debug(f"女声变音后长度: {len(audio_bytes)}")
            else:
                logging.debug("使用原声")
                audio_bytes = VoiceChanger.apply_original_voice(audio_bytes)
            
            # 最终验证
            if len(audio_bytes) == 0:
                QMessageBox.warning(self, "错误", "变音处理后音频数据为空")
                return
            
            # 发送信号
            self.voice_message_ready.emit(audio_bytes, self.voice_type)
            self.accept()
            
        except Exception as e:
            logging.error(f"处理语音消息失败: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "发送失败", f"处理语音消息失败: {e}")

    def closeEvent(self, event):
        """关闭对话框时清理资源"""
        if self.recording:
            self.stop_recording()
        event.accept()


class AudioDeviceSelector(QDialog):
    """音频设备选择对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择音频设备")
        self.setFixedSize(400, 300)

        self.audio = pyaudio.PyAudio()
        self.selected_devices = {'input': None, 'output': None}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 输入设备选择
        input_layout = QVBoxLayout()
        input_layout.addWidget(QLabel("选择输入设备:"))
        self.input_combo = QComboBox()
        self.populate_input_devices()
        input_layout.addWidget(self.input_combo)

        # 输出设备选择
        output_layout = QVBoxLayout()
        output_layout.addWidget(QLabel("选择输出设备:"))
        self.output_combo = QComboBox()
        self.populate_output_devices()
        output_layout.addWidget(self.output_combo)

        # 按钮区域
        button_layout = QHBoxLayout()
        self.test_btn = QPushButton("测试设备")
        self.test_btn.clicked.connect(self.test_devices)
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.test_btn)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(input_layout)
        layout.addLayout(output_layout)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def populate_input_devices(self):
        default_input = None
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if device_info['maxInputChannels'] > 0:  # 只显示有输入功能的设备
                self.input_combo.addItem(device_info['name'], i)
                # 设置默认输入设备
                if device_info.get('defaultSampleRate', 0) > 0 and default_input is None:
                    default_input = self.input_combo.count() - 1
        
        # 设置默认选择
        if default_input is not None:
            self.input_combo.setCurrentIndex(default_input)

    def populate_output_devices(self):
        default_output = None
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if device_info['maxOutputChannels'] > 0:  # 只显示有输出功能的设备
                self.output_combo.addItem(device_info['name'], i)
                # 设置默认输出设备
                if device_info.get('defaultSampleRate', 0) > 0 and default_output is None:
                    default_output = self.output_combo.count() - 1
        
        # 设置默认选择
        if default_output is not None:
            self.output_combo.setCurrentIndex(default_output)

    def get_selected_devices(self):
        return {
            'input': self.input_combo.currentData(),
            'output': self.output_combo.currentData()
        }

    def accept(self):
        # 验证设备选择
        input_device = self.input_combo.currentData()
        output_device = self.output_combo.currentData()
        
        if input_device is None or output_device is None:
            QMessageBox.warning(self, "设备选择错误", "请选择有效的输入和输出设备")
            return
        
        self.selected_devices = {
            'input': input_device,
            'output': output_device
        }
        super().accept()

    def closeEvent(self, event):
        self.audio.terminate()
        event.accept()

    def test_devices(self):
        """测试选中的音频设备"""
        try:
            input_device = self.input_combo.currentData()
            output_device = self.output_combo.currentData()
            
            if input_device is None or output_device is None:
                QMessageBox.warning(self, "设备选择错误", "请先选择输入和输出设备")
                return
            
            # 显示测试对话框
            test_dialog = QMessageBox(self)
            test_dialog.setWindowTitle("设备测试")
            test_dialog.setText("正在测试音频设备...\n请对着麦克风说话，您应该能听到自己的声音")
            test_dialog.setStandardButtons(QMessageBox.Cancel)
            test_dialog.setModal(False)
            test_dialog.show()
            
            # 创建测试音频流
            test_stream_in = None
            test_stream_out = None
            
            try:
                # 打开输入流
                test_stream_in = self.audio.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    input_device_index=input_device,
                    frames_per_buffer=CHUNK
                )
                
                # 打开输出流
                test_stream_out = self.audio.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    output=True,
                    output_device_index=output_device,
                    frames_per_buffer=CHUNK
                )
                
                # 测试3秒钟
                for i in range(int(3 * RATE / CHUNK)):
                    if test_dialog.result() == QMessageBox.Cancel:
                        break
                    
                    # 读取音频数据
                    data = test_stream_in.read(CHUNK, exception_on_overflow=False)
                    # 降低音量以避免反馈
                    reduced_data = audioop.mul(data, 2, 0.3)
                    # 播放音频数据
                    test_stream_out.write(reduced_data)
                    
                    QApplication.processEvents()
                
                test_dialog.close()
                QMessageBox.information(self, "测试完成", "音频设备测试完成！\n如果您听到了自己的声音，说明设备工作正常。")
                
            except Exception as e:
                test_dialog.close()
                QMessageBox.warning(self, "测试失败", f"音频设备测试失败: {e}")
            finally:
                # 清理测试流
                if test_stream_in:
                    test_stream_in.stop_stream()
                    test_stream_in.close()
                if test_stream_out:
                    test_stream_out.stop_stream()
                    test_stream_out.close()
                    
        except Exception as e:
            QMessageBox.warning(self, "测试错误", f"无法测试音频设备: {e}")


class AudioRecorder(QThread):
    """音频录制线程"""

    def __init__(self, udp_thread, target_addr, sender, receiver, input_device_index=None):
        super().__init__()
        self.udp_thread = udp_thread
        self.target_addr = target_addr
        self.sender = sender
        self.receiver = receiver
        self.running = True
        self.audio = None
        self.stream = None
        self.error_occurred = False
        self.input_device_index = input_device_index
        self.packet_count = 0
        logging.debug(f"初始化音频录制器: input_device_index={input_device_index}")

    def run(self):
        try:
            # 初始化音频设备
            self.audio = pyaudio.PyAudio()

            # 验证输入设备索引
            if self.input_device_index is None:
                # 使用默认输入设备
                self.input_device_index = self.audio.get_default_input_device_info()['index']
                logging.debug(f"使用默认输入设备: {self.input_device_index}")

            # 获取输入设备信息
            device_info = self.audio.get_device_info_by_index(self.input_device_index)
            logging.debug(f"使用输入设备: {device_info['name']}")
            logging.debug(f"设备信息: {device_info}")

            # 打开音频流，使用更大的缓冲区以减少丢包
            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                input_device_index=self.input_device_index,
                stream_callback=None,
                start=False
            )

            # 启动流
            self.stream.start_stream()
            logging.debug("开始录音...")

            # 持续录制和发送音频
            while self.running and not self.error_occurred:
                if self.stream and self.stream.is_active():
                    try:
                        # 使用exception_on_overflow=False避免因缓冲区溢出而丢失数据
                        audio_data = self.stream.read(CHUNK, exception_on_overflow=False)
                        if audio_data and len(audio_data) > 0:
                            self.packet_count += 1
                            # 每录制100个包记录一次日志
                            if self.packet_count % 100 == 0:
                                logging.debug(f"录制到音频数据: 包 #{self.packet_count}, {len(audio_data)} 字节")
                            
                            # 验证目标地址
                            if self.target_addr and len(self.target_addr) == 2:
                                # 应用回声抑制
                                echo_suppressed = AudioCompressor.apply_echo_suppression(audio_data)
                                # 应用音频压缩
                                compressed_audio = AudioCompressor.compress_audio(echo_suppressed, compression_level=2)
                                self.udp_thread.send_audio(compressed_audio, self.target_addr, self.sender, self.receiver)
                            else:
                                logging.warning(f"无效的目标地址: {self.target_addr}")
                        else:
                            logging.warning(f"录制到空音频数据")
                    except Exception as e:
                        logging.error(f"录音错误: {e}")
                        # 不要立即将error_occurred设为True，尝试恢复
                        time.sleep(0.1)
                else:
                    logging.warning("音频流未激活，尝试重新启动...")
                    try:
                        if self.stream:
                            if not self.stream.is_active():
                                self.stream.start_stream()
                                logging.debug("已重新启动音频流")
                    except Exception as e:
                        logging.error(f"重启音频流失败: {e}")
                    time.sleep(0.5)
        except Exception as e:
            logging.error(f"录音初始化错误: {e}")
            self.error_occurred = True
        finally:
            self.stop_recording()

    def stop_recording(self):
        if self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                print(f"关闭录音流错误: {e}")
            finally:
                self.stream = None

    def stop(self):
        self.running = False
        self.stop_recording()
        if self.audio:
            try:
                self.audio.terminate()
            except Exception as e:
                print(f"终止音频设备错误: {e}")
        self.quit()
        self.wait()


class AudioPlayer(QThread):
    """音频播放线程"""

    def __init__(self, output_device_index=None):
        super().__init__()
        self.audio = None
        self.stream = None
        self.running = True
        self.audio_queue = []
        self.queue_lock = threading.Lock()
        self.error_occurred = False
        self.output_device_index = output_device_index
        self.play_count = 0
        logging.debug(f"初始化音频播放器: output_device_index={output_device_index}")

    def run(self):
        try:
            # 初始化音频设备
            self.audio = pyaudio.PyAudio()

            # 验证输出设备索引
            if self.output_device_index is None:
                # 使用默认输出设备
                self.output_device_index = self.audio.get_default_output_device_info()['index']
                logging.debug(f"使用默认输出设备: {self.output_device_index}")

            # 获取输出设备信息
            device_info = self.audio.get_device_info_by_index(self.output_device_index)
            logging.debug(f"使用输出设备: {device_info['name']}")
            logging.debug(f"设备信息: {device_info}")

            # 打开音频流
            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                frames_per_buffer=CHUNK,
                output_device_index=self.output_device_index,
                stream_callback=None,
                start=True  # 改为True，确保流立即启动
            )

            logging.debug("开始音频播放...")

            # 持续从队列中获取和播放音频
            while self.running and not self.error_occurred:
                if self.audio_queue and self.stream and self.stream.is_active():
                    try:
                        with self.queue_lock:
                            if self.audio_queue:
                                audio_data = self.audio_queue.pop(0)
                                if audio_data and len(audio_data) > 0:
                                    self.play_count += 1
                                    # 每播放100个包记录一次日志
                                    if self.play_count % 100 == 0:
                                        logging.debug(f"播放音频数据: 包 #{self.play_count}, {len(audio_data)} 字节")
                                    # 直接播放音频数据（语音消息不需要解压缩）
                                    self.stream.write(audio_data)
                    except Exception as e:
                        logging.error(f"播放错误: {e}")
                        self.error_occurred = True
                        time.sleep(0.01)
                else:
                    time.sleep(0.01)
        except Exception as e:
            logging.error(f"播放初始化错误: {e}")
            self.error_occurred = True
        finally:
            self.stop_playback()

    def add_audio(self, audio_data):
        if not audio_data or len(audio_data) == 0:
            return

        with self.queue_lock:
            # 限制队列大小，防止延迟过大
            if len(self.audio_queue) > 20:  # 增加队列大小以减少丢包
                self.audio_queue = self.audio_queue[10:]  # 丢弃一些旧的数据
            self.audio_queue.append(audio_data)

    def stop_playback(self):
        if self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                print(f"关闭播放流错误: {e}")
            finally:
                self.stream = None

    def stop(self):
        self.running = False
        self.stop_playback()
        if self.audio:
            try:
                self.audio.terminate()
            except Exception as e:
                print(f"终止音频设备错误: {e}")
        self.quit()
        self.wait()


class VoiceMessageAudioPlayer(QThread):
    """专门用于语音消息播放的音频播放器"""

    def __init__(self):
        super().__init__()
        self.audio = None
        self.stream = None
        self.running = True
        self.audio_queue = []
        self.queue_lock = threading.Lock()
        self.error_occurred = False
        logging.debug("初始化语音消息音频播放器")

    def run(self):
        try:
            # 初始化音频设备
            self.audio = pyaudio.PyAudio()

            # 使用默认输出设备
            output_device_index = self.audio.get_default_output_device_info()['index']
            logging.debug(f"使用默认输出设备: {output_device_index}")

            # 打开音频流
            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                frames_per_buffer=CHUNK,
                output_device_index=output_device_index,
                stream_callback=None,
                start=True
            )

            logging.debug("语音消息播放器开始运行...")

                        # 持续从队列中获取和播放音频
            while self.running and not self.error_occurred:
                if self.audio_queue and self.stream and self.stream.is_active():
                    try:
                        with self.queue_lock:
                            if self.audio_queue:
                                audio_data = self.audio_queue.pop(0)
                                if audio_data and len(audio_data) > 0:
                                    # 直接播放音频数据
                                    self.stream.write(audio_data)
                    except Exception as e:
                        logging.error(f"语音消息播放错误: {e}")
                        self.error_occurred = True
                        time.sleep(0.01)
                else:
                    time.sleep(0.01)
        except Exception as e:
            logging.error(f"语音消息播放器初始化错误: {e}")
            self.error_occurred = True
        finally:
            self.stop_playback()

    def add_audio(self, audio_data):
        if not audio_data or len(audio_data) == 0:
            return

        with self.queue_lock:
            self.audio_queue.append(audio_data)

    def stop_playback(self):
        if self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                logging.error(f"关闭语音消息播放流错误: {e}")
            finally:
                self.stream = None

    def stop(self):
        self.running = False
        self.stop_playback()
        if self.audio:
            try:
                self.audio.terminate()
            except Exception as e:
                logging.error(f"终止语音消息音频设备错误: {e}")
        self.quit()
        self.wait()


# 移除所有语音通话相关的对话框类


def excepthook(type, value, traceback):
    QMessageBox.critical(None, '未捕获异常', str(value))
    sys.__excepthook__(type, value, traceback)


sys.excepthook = excepthook


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('登录/注册')

        # 检查网络配置
        if not check_network_config():
            sys.exit(1)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((SERVER_HOST, SERVER_PORT))
        except Exception as e:
            QMessageBox.critical(self, '错误', f'无法连接服务器: {e}')
            sys.exit(1)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText('用户名')
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setPlaceholderText('密码')
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.login_btn = QPushButton('登录')
        self.reg_btn = QPushButton('注册')
        self.del_btn = QPushButton('注销')
        self.login_btn.clicked.connect(self.login)
        self.reg_btn.clicked.connect(self.register)
        self.del_btn.clicked.connect(self.delete_user)
        layout.addWidget(QLabel('用户名:'))
        layout.addWidget(self.user_edit)
        layout.addWidget(QLabel('密码:'))
        layout.addWidget(self.pwd_edit)
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.login_btn)
        btn_layout.addWidget(self.reg_btn)
        btn_layout.addWidget(self.del_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def login(self):
        username = self.user_edit.text().strip()
        password = self.pwd_edit.text().strip()
        if not username or not password:
            QMessageBox.warning(self, '提示', '请输入用户名和密码')
            return
        
        # 确保消息以换行符结尾
        login_msg = f'LOGIN|{username}|{password}\n'
        self.sock.send(login_msg.encode('utf-8'))
        
        try:
            resp = self.sock.recv(16384).decode('utf-8')
        except Exception as e:
            QMessageBox.critical(self, '错误', f'网络错误: {e}')
            return
        parts = resp.split('|', 2)
        if parts[0] == 'LOGIN_RESULT' and parts[1] == 'OK':
            self.accept_login(username)
        else:
            QMessageBox.warning(self, '登录失败', parts[2] if len(parts) > 2 else '未知错误')
            self.show()  # 保证窗口不关闭

    def register(self):
        username = self.user_edit.text().strip()
        password = self.pwd_edit.text().strip()
        if not username or not password:
            QMessageBox.warning(self, '提示', '请输入用户名和密码')
            return
        
        # 确保消息以换行符结尾
        register_msg = f'REGISTER|{username}|{password}\n'
        self.sock.send(register_msg.encode('utf-8'))
        
        resp = self.sock.recv(16384).decode('utf-8')
        parts = resp.split('|', 2)
        if parts[0] == 'REGISTER_RESULT' and parts[1] == 'OK':
            QMessageBox.information(self, '注册成功', parts[2])
        else:
            QMessageBox.warning(self, '注册失败', parts[2] if len(parts) > 2 else '未知错误')

    def delete_user(self):
        username = self.user_edit.text().strip()
        password = self.pwd_edit.text().strip()
        if not username or not password:
            QMessageBox.warning(self, '提示', '请输入用户名和密码')
            return
        try:
            # 确保消息以换行符结尾
            delete_msg = f'DELETE_USER|{username}|{password}\n'
            self.sock.send(delete_msg.encode('utf-8'))
            
            resp = self.sock.recv(16384).decode('utf-8')
            parts = resp.split('|', 2)
            if parts[0] == 'DELETE_USER_RESULT' and parts[1] == 'OK':
                QMessageBox.information(self, '注销成功', '账号已注销，您可以重新注册同名账号。')
                self.user_edit.clear()
                self.pwd_edit.clear()
            else:
                QMessageBox.warning(self, '注销失败', '用户名或密码错误，或账号不存在。')
        except Exception as e:
            QMessageBox.critical(self, '错误', f'注销请求失败: {e}')

    def accept_login(self, username):
        try:
            self.hide()
            self.main_win = MainWindow(self.sock, username)
            self.main_win.show()
        except Exception as e:
            QMessageBox.critical(self, '错误', f'登录后主窗口异常: {e}')
            self.show()


class EmojiDialog(QWidget):
    emoji_selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('选择表情')
        self.layout = QVBoxLayout()  # 改为垂直布局
        self.setLayout(self.layout)
        self.setWindowFlags(self.windowFlags() | Qt.Tool)
        # 表情按钮区
        self.emoji_layout = QHBoxLayout()
        self.layout.addLayout(self.emoji_layout)
        # 上传按钮
        self.upload_btn = QPushButton('上传表情')
        self.upload_btn.clicked.connect(self.upload_emoji)
        self.layout.addWidget(self.upload_btn)
        self.load_emojis()

    def load_emojis(self):
        # 清空原有按钮
        while self.emoji_layout.count():
            item = self.emoji_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not os.path.exists(EMOJI_DIR):
            return
        for fname in os.listdir(EMOJI_DIR):
            if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                btn = QPushButton()
                btn.setIcon(QIcon(os.path.join(EMOJI_DIR, fname)))
                btn.setIconSize(QPixmap(os.path.join(EMOJI_DIR, fname)).size())
                btn.setFixedSize(40, 40)
                btn.clicked.connect(lambda _, f=fname: self.emoji_selected.emit(f))
                self.emoji_layout.addWidget(btn)

    def upload_emoji(self):
        file_path, _ = QFileDialog.getOpenFileName(self, '选择表情图片', '', 'Images (*.png *.jpg *.jpeg *.gif)')
        if file_path:
            fname = os.path.basename(file_path)
            dest_path = os.path.join(EMOJI_DIR, fname)
            # 避免重名覆盖
            base, ext = os.path.splitext(fname)
            i = 1
            while os.path.exists(dest_path):
                fname = f"{base}_{i}{ext}"
                dest_path = os.path.join(EMOJI_DIR, fname)
                i += 1
            try:
                shutil.copy(file_path, dest_path)
                QMessageBox.information(self, '上传成功', '表情已添加！')
                self.load_emojis()
            except Exception as e:
                QMessageBox.warning(self, '上传失败', f'无法添加表情: {e}')


class VoiceMessagePlayer(QWidget):
    """语音消息播放器组件"""
    
    def __init__(self, audio_data, voice_type="original", duration=0):
        super().__init__()
        self.audio_data = audio_data
        self.voice_type = voice_type
        self.duration = duration
        self.playing = False
        self.audio_player = None
        
        self.init_ui()
    
    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 播放按钮
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(30, 30)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        self.play_btn.clicked.connect(self.toggle_play)
        
        # 语音类型标识
        voice_icon = "🎤" if self.voice_type == "original" else "👩"
        self.voice_label = QLabel(f"{voice_icon} 语音消息")
        self.voice_label.setStyleSheet("color: #666; font-size: 10pt;")
        
        # 时长显示
        duration_text = f"{int(self.duration)}秒" if self.duration > 0 else "语音"
        self.duration_label = QLabel(duration_text)
        self.duration_label.setStyleSheet("color: #999; font-size: 9pt;")
        
        layout.addWidget(self.play_btn)
        layout.addWidget(self.voice_label)
        layout.addWidget(self.duration_label)
        layout.addStretch()
        
        self.setLayout(layout)
        self.setFixedHeight(40)
        self.setStyleSheet("""
            QWidget {
                background-color: #f0f8ff;
                border: 1px solid #ccc;
                border-radius: 8px;
            }
        """)
    
    def toggle_play(self):
        """切换播放状态"""
        if not self.playing:
            self.start_play()
        else:
            self.stop_play()
    
    def start_play(self):
        """开始播放"""
        try:
            if not self.audio_data or len(self.audio_data) == 0:
                logging.warning("音频数据为空，无法播放")
                return
            
            self.playing = True
            self.play_btn.setText("⏸")
            self.voice_label.setText("🔊 正在播放...")
            
            logging.debug(f"开始播放语音消息，数据长度: {len(self.audio_data)} 字节")
            
            # 使用简化的播放方法
            import threading
            def play_audio():
                audio = None
                stream = None
                try:
                    audio = pyaudio.PyAudio()
                    
                    # 验证音频格式
                    try:
                        stream = audio.open(
                            format=FORMAT,
                            channels=CHANNELS,
                            rate=RATE,
                            output=True,
                            frames_per_buffer=CHUNK
                        )
                        logging.debug("音频流创建成功")
                    except Exception as stream_error:
                        logging.error(f"创建音频流失败: {stream_error}")
                        raise stream_error
                    
                    # 验证音频数据长度
                    if len(self.audio_data) % 2 != 0:
                        # 如果数据长度为奇数，去掉最后一个字节
                        audio_data = self.audio_data[:-1]
                        logging.warning("音频数据长度为奇数，已调整")
                    else:
                        audio_data = self.audio_data
                    
                    # 分块播放音频数据
                    chunk_size = CHUNK * 2  # 每个样本2字节
                    total_chunks = len(audio_data) // chunk_size
                    logging.debug(f"总共需要播放 {total_chunks} 个音频块")
                    
                    for i in range(0, len(audio_data), chunk_size):
                        if not self.playing:  # 检查是否被停止
                            logging.debug("播放被用户停止")
                            break
                        
                        chunk = audio_data[i:i + chunk_size]
                        if len(chunk) > 0:
                            try:
                                stream.write(chunk)
                            except Exception as write_error:
                                logging.error(f"写入音频数据失败: {write_error}")
                                break
                    
                    logging.debug("音频播放完成")
                    
                except Exception as e:
                    logging.error(f"播放音频失败: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    # 清理资源
                    if stream:
                        try:
                            stream.stop_stream()
                            stream.close()
                        except:
                            pass
                    if audio:
                        try:
                            audio.terminate()
                        except:
                            pass
                    
                    # 播放完成后重置UI
                    QTimer.singleShot(100, self.on_play_finished)
            
            # 在新线程中播放音频
            threading.Thread(target=play_audio, daemon=True).start()
            
        except Exception as e:
            logging.error(f"启动语音消息播放失败: {e}")
            import traceback
            traceback.print_exc()
            self.stop_play()
    
    def stop_play(self):
        """停止播放"""
        self.playing = False
        self.play_btn.setText("▶")
        voice_icon = "🎤" if self.voice_type == "original" else "👩"
        self.voice_label.setText(f"{voice_icon} 语音消息")
    
    def on_play_finished(self):
        """播放完成回调"""
        if self.playing:
            self.stop_play()


class MainWindow(QWidget):
    def __init__(self, sock, username):
        super().__init__()
        logging.debug(f"初始化主窗口: 用户={username}")
        self.sock = sock
        self.username = username
        self.setWindowTitle(f'聊天 - {username}')
        self.current_friend = None
        self.current_group = None
        self.friends = []
        self.friend_status = {}
        self.unread_groups = set()  # 有未读消息的群
        self.anon_mode = False  # 匿名模式
        self.anon_nick = None  # 匿名昵称
        self.selecting_group = False  # 防止群聊选择的重入调用

        # 移除语音通话相关变量，保留UDP线程用于其他功能
        self.udp_thread = None
        self.udp_local_port = None

        # 加载表情缓存
        self.emoji_cache = {}

        logging.debug(f"创建客户端线程")
        # 创建客户端线程
        self.client_thread = ClientThread(sock)
        self.client_thread.message_received.connect(self.on_message)
        self.client_thread.connection_lost.connect(self.on_connection_lost)
        self.client_thread.start()

        # 移除UDP音频服务初始化

        # 预加载表情
        self.preload_emojis()

        logging.debug(f"初始化UI")
        self.init_ui()

        logging.debug(f"初始刷新好友和群组列表")
        self.initial_refresh()

        # 移除语音通话相关的定时器和变量

        logging.debug(f"主窗口初始化完成，用户: {username}, UDP端口: {self.udp_local_port}")
        center_window(self)  # 居中显示窗口
        # 在MainWindow.__init__中添加self.current_bg_index = 0
        self.current_bg_index = 0
        self.private_files = []  # 当前私聊文件列表

    def send_message_to_server(self, message):
        """统一的消息发送方法，确保格式正确"""
        try:
            if not message.endswith('\n'):
                message += '\n'
            
            encoded_msg = message.encode('utf-8')
            logging.debug(f"发送消息: {message.strip()}, 长度: {len(encoded_msg)} 字节")
            self.sock.send(encoded_msg)
            return True
        except Exception as e:
            logging.error(f"发送消息失败: {e}")
            return False

    def init_udp_audio(self):
        """初始化UDP音频通信"""
        logging.debug("开始初始化UDP音频服务")

        # 为了避免在同一台计算机上测试时的冲突，使用随机端口而不是基于用户名
        self.udp_local_port = random.randint(40000, 65000)
        logging.debug(f"分配随机UDP端口: {self.udp_local_port}")

        # 确保端口不被占用
        port_attempts = 0
        while port_attempts < 20:  # 增加尝试次数
            try:
                logging.debug(f"尝试绑定UDP端口: {self.udp_local_port}")
                test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                test_socket.bind(('0.0.0.0', self.udp_local_port))
                test_socket.close()
                logging.debug(f"UDP端口绑定成功: {self.udp_local_port}")
                break
            except Exception as e:
                port_attempts += 1
                logging.warning(f"UDP端口 {self.udp_local_port} 绑定失败: {e}，尝试下一个端口")
                self.udp_local_port = random.randint(40000, 65000)  # 使用新的随机端口

        if port_attempts >= 20:
            logging.error("无法找到可用的UDP端口")
            QMessageBox.warning(self, '错误', '无法初始化语音通话功能，找不到可用端口')
            return

        # 创建UDP音频线程
        try:
            logging.debug(f"创建UDP音频线程，端口: {self.udp_local_port}")
            self.udp_thread = UDPAudioThread(self.udp_local_port)
            self.udp_thread.start()
            logging.debug("UDP音频线程启动成功")
        except Exception as e:
            logging.error(f"创建UDP音频线程失败: {e}", exc_info=True)
            QMessageBox.warning(self, '错误', f'初始化语音通话功能失败: {e}')

        # 通知服务器我们的UDP端口
        try:
            update_msg = f'UDP_PORT_UPDATE|{self.username}|{self.udp_local_port}'
            logging.debug(f"发送UDP端口更新消息: {update_msg}")
            self.send_message_to_server(update_msg)
        except Exception as e:
            logging.error(f"发送UDP端口更新消息失败: {e}")

        logging.debug(f"UDP音频服务初始化完成，端口: {self.udp_local_port}")

    def preload_emojis(self):
        """预加载所有表情到缓存"""
        try:
            if not os.path.exists(EMOJI_DIR):
                logging.debug("表情目录不存在，跳过预加载")
                return

            logging.debug("开始预加载表情...")
            emoji_count = 0
            for fname in os.listdir(EMOJI_DIR):
                try:
                    if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                        path = os.path.join(EMOJI_DIR, fname)
                        if not os.path.exists(path):
                            logging.warning(f"表情文件不存在: {path}")
                            continue
                            
                        if fname.lower().endswith('.gif'):
                            # 加载GIF - 保存路径而不是QMovie实例
                            try:
                                movie = QMovie(path)
                                movie.setCacheMode(QMovie.CacheAll)
                                self.emoji_cache[fname] = {'type': 'gif', 'movie': movie, 'path': path}
                                emoji_count += 1
                            except Exception as gif_error:
                                logging.warning(f"加载GIF表情失败: {fname}, 错误: {gif_error}")
                        else:
                            # 加载静态图片
                            try:
                                pix = QPixmap(path)
                                if not pix.isNull():
                                    scaled_pix = pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                    self.emoji_cache[fname] = {'type': 'image', 'pixmap': scaled_pix}
                                    emoji_count += 1
                                else:
                                    logging.warning(f"无法加载图片表情: {fname}")
                            except Exception as img_error:
                                logging.warning(f"加载图片表情失败: {fname}, 错误: {img_error}")
                except Exception as file_error:
                    logging.warning(f"处理表情文件失败: {fname}, 错误: {file_error}")
                    continue
                    
            logging.debug(f"预加载完成，共 {emoji_count} 个表情")
        except Exception as e:
            logging.error(f"预加载表情出错: {e}")
            # 即使预加载失败也不应该阻塞程序启动

    def get_emoji_from_cache(self, emoji_id, label):
        """从缓存获取表情并设置到标签"""
        if emoji_id in self.emoji_cache:
            emoji_data = self.emoji_cache[emoji_id]
            if emoji_data['type'] == 'gif':
                # 为每个标签创建新的QMovie实例，避免共享问题
                movie = QMovie(emoji_data['path'])
                movie.setCacheMode(QMovie.CacheAll)
                label.setMovie(movie)
                movie.start()
                # 保存movie引用到label，防止被垃圾回收
                label.movie_ref = movie
            else:
                label.setPixmap(emoji_data['pixmap'])
            return True
        return False

    def init_ui(self):
        main_layout = QHBoxLayout()
        # 好友/群聊列表
        left_layout = QVBoxLayout()
        self.refresh_friends_btn = QPushButton('刷新好友')
        self.refresh_friends_btn.clicked.connect(self.get_friends)
        left_layout.addWidget(self.refresh_friends_btn)
        self.friend_list = QListWidget()
        self.friend_list.itemClicked.connect(self.select_friend)
        self.add_friend_btn = QPushButton('添加好友')
        self.del_friend_btn = QPushButton('删除好友')
        self.add_friend_btn.clicked.connect(self.add_friend)
        self.del_friend_btn.clicked.connect(self.del_friend)
        left_layout.addWidget(QLabel('好友列表'))
        left_layout.addWidget(self.friend_list)
        left_layout.addWidget(self.add_friend_btn)
        left_layout.addWidget(self.del_friend_btn)
        # 群聊列表
        self.group_list = QListWidget()
        self.group_list.itemClicked.connect(self.select_group)
        self.create_group_btn = QPushButton('创建群聊')
        self.join_group_btn = QPushButton('加入群聊')
        self.create_group_btn.clicked.connect(self.create_group)
        self.join_group_btn.clicked.connect(self.join_group)
        left_layout.addWidget(QLabel('群聊列表'))
        left_layout.addWidget(self.group_list)
        left_layout.addWidget(self.create_group_btn)
        left_layout.addWidget(self.join_group_btn)
        # 聊天区
        right_layout = QVBoxLayout()
        self.tab_widget = QTabWidget()
        self.private_tab = QWidget()
        self.group_tab = QWidget()
        self.tab_widget.addTab(self.private_tab, '私聊')
        self.tab_widget.addTab(self.group_tab, '群聊')
        # 私聊区
        private_layout = QVBoxLayout()
        self.chat_display = QListWidget()
        private_layout.addWidget(self.chat_display)
        # 文件区
        file_layout = QHBoxLayout()
        self.upload_file_btn = QPushButton('上传文件')
        self.upload_file_btn.clicked.connect(self.upload_private_file)
        self.file_list = QListWidget()
        self.file_list.setFixedHeight(80)
        self.file_list.itemDoubleClicked.connect(self.download_private_file)
        file_layout.addWidget(self.upload_file_btn)
        file_layout.addWidget(self.file_list)
        private_layout.addLayout(file_layout)
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText('输入消息...')
        self.send_btn = QPushButton('发送')
        self.send_btn.clicked.connect(self.send_message)
        self.emoji_btn = QPushButton('😀')
        self.emoji_btn.setFixedWidth(40)
        self.emoji_btn.clicked.connect(self.open_emoji_dialog)
        # 添加语音消息按钮
        self.voice_btn = QPushButton('🎤')
        self.voice_btn.setFixedWidth(40)
        self.voice_btn.setToolTip('发送语音消息')
        self.voice_btn.clicked.connect(self.send_voice_message)
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.emoji_btn)
        input_layout.addWidget(self.voice_btn)
        input_layout.addWidget(self.send_btn)
        private_layout.addLayout(input_layout)
        self.private_tab.setLayout(private_layout)
        # 群聊区
        group_layout = QVBoxLayout()
        self.group_chat_display = QListWidget()
        group_layout.addWidget(self.group_chat_display)
        group_input_layout = QHBoxLayout()
        self.group_input_edit = QLineEdit()
        self.group_input_edit.setPlaceholderText('输入群聊消息...')
        self.group_send_btn = QPushButton('发送')
        self.group_send_btn.clicked.connect(self.send_group_message)
        self.group_emoji_btn = QPushButton('😀')
        self.group_emoji_btn.setFixedWidth(40)
        self.group_emoji_btn.clicked.connect(self.open_emoji_dialog)
        self.group_anon_btn = QPushButton('匿名')
        self.group_anon_btn.setCheckable(True)
        self.group_anon_btn.clicked.connect(self.toggle_anon_mode)
        group_input_layout.addWidget(self.group_input_edit)
        group_input_layout.addWidget(self.group_emoji_btn)
        group_input_layout.addWidget(self.group_anon_btn)
        group_input_layout.addWidget(self.group_send_btn)
        group_layout.addLayout(group_input_layout)
        # 群成员显示
        self.group_members_label = QLabel('群成员:')
        self.group_members_list = QListWidget()
        group_layout.addWidget(self.group_members_label)
        group_layout.addWidget(self.group_members_list)
        self.group_tab.setLayout(group_layout)
        right_layout.addWidget(self.tab_widget)
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 3)
        self.setLayout(main_layout)
        self.emoji_dialog = None
        # 在MainWindow.init_ui()的main_layout定义后添加背景切换按钮和分辨率调整按钮
        self.bg_btn = QPushButton('切换背景')
        self.bg_btn.setToolTip('切换聊天背景')
        self.bg_btn.clicked.connect(self.switch_background)
        self.resolution_btn = QPushButton('调整分辨率')
        self.resolution_btn.setToolTip('调整界面分辨率')
        self.resolution_btn.clicked.connect(self.change_resolution)
        right_layout.addWidget(self.bg_btn)
        right_layout.addWidget(self.resolution_btn)

    def get_friends(self):
        try:
            self.send_message_to_server(f'GET_FRIENDS|{self.username}')
        except Exception as e:
            print(f"获取好友列表出错: {e}")
            QMessageBox.warning(self, '网络错误', '获取好友列表失败，请检查网络连接')

    def get_groups(self):
        try:
            self.send_message_to_server(f'GET_GROUPS|{self.username}')
            # 清空未读标记
            self.unread_groups = set()
        except Exception as e:
            print(f"获取群聊列表出错: {e}")
            QMessageBox.warning(self, '网络错误', '获取群聊列表失败，请检查网络连接')

    def select_friend(self, item):
        self.current_friend = item.text().split(' ')[0]
        self.chat_display.clear()
        self.append_text_message('', f'与 {self.current_friend} 的聊天：')
        self.get_private_history()
        self.load_and_display_voice_history()
        self.get_private_file_list()

    def load_and_display_voice_history(self):
        """加载并显示语音消息历史"""
        if not self.current_friend:
            return
        
        try:
            voice_history = self.load_voice_message_history(self.current_friend)
            for record in voice_history:
                try:
                    # 解码音频数据
                    import base64
                    audio_base64 = record['audio_base64']
                    try:
                        # 修复base64填充问题
                        missing_padding = len(audio_base64) % 4
                        if missing_padding:
                            audio_base64 += '=' * (4 - missing_padding)
                        audio_data = base64.b64decode(audio_base64.encode('utf-8'))
                    except Exception as decode_error:
                        logging.error(f"语音消息历史记录base64解码失败: {decode_error}")
                        continue  # 跳过这条损坏的语音消息
                    
                    # 显示语音消息
                    sender = record['sender']
                    voice_type = record['voice_type']
                    duration = record['duration']
                    
                    is_self = (sender == self.username)
                    display_sender = '我' if is_self else sender
                    
                    self.append_voice_message(display_sender, audio_data, voice_type, duration, is_self)
                    
                except Exception as e:
                    logging.error(f"显示语音消息历史失败: {e}")
                    
        except Exception as e:
            logging.error(f"加载语音消息历史失败: {e}")

    def get_private_history(self):
        """获取与当前好友的私聊历史记录"""
        if not self.current_friend:
            return
        try:
            self.send_message_to_server(f'GET_PRIVATE_HISTORY|{self.username}|{self.current_friend}')
        except Exception as e:
            print(f"获取私聊历史记录出错: {e}")
            self.append_text_message('[系统]', '获取聊天记录失败，请检查网络连接')

    def add_friend(self):
        friend, ok = QInputDialog.getText(self, '添加好友', '输入好友用户名:')
        if ok and friend:
            self.send_message_to_server(f'ADD_FRIEND|{self.username}|{friend}')

    def del_friend(self):
        if not self.current_friend:
            QMessageBox.warning(self, '提示', '请先选择要删除的好友')
            return
        self.send_message_to_server(f'DEL_FRIEND|{self.username}|{self.current_friend}')

    def append_text_message(self, sender, text, is_self=False):
        label = QLabel()
        label.setText(f'<b>{sender}:</b> {text}')
        item = QListWidgetItem()
        self.chat_display.addItem(item)
        self.chat_display.setItemWidget(item, label)
        item.setSizeHint(label.sizeHint())
        if is_self:
            label.setStyleSheet('color:blue;')
        self.chat_display.scrollToBottom()

    def append_emoji_message(self, sender, emoji_id):
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel(f'<b>{sender}:</b>')
        img_label = QLabel()

        # 尝试从缓存获取表情
        if not self.get_emoji_from_cache(emoji_id, img_label):
            path = os.path.join(EMOJI_DIR, emoji_id)

            # 添加路径检查
            if not os.path.exists(path):
                print(f"表情文件不存在: {path}")
                img_label.setText(f"[表情: {emoji_id}]")
            elif emoji_id.lower().endswith('.gif'):
                # 使用定时器确保GIF加载完成
                movie = QMovie(path)
                img_label.setMovie(movie)
                movie.setCacheMode(QMovie.CacheAll)
                movie.start()
                # 强制处理事件以确保显示更新
                QApplication.processEvents()
            else:
                # 静态图片加载
                pix = QPixmap(path)
                if pix.isNull():
                    # 如果加载失败，尝试重新加载
                    print(f"表情加载失败，尝试重新加载: {emoji_id}")
                    pix = QPixmap(path)
                img_label.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                # 强制处理事件以确保显示更新
                QApplication.processEvents()

        layout.addWidget(name_label)
        layout.addWidget(img_label)
        widget.setLayout(layout)
        item = QListWidgetItem()
        self.chat_display.addItem(item)
        self.chat_display.setItemWidget(item, widget)
        item.setSizeHint(widget.sizeHint())
        self.chat_display.scrollToBottom()
        # 强制刷新UI
        self.chat_display.repaint()

    def send_message(self):
        msg = self.input_edit.text().strip()
        if not msg or not self.current_friend:
            return
        self.send_message_to_server(f'MSG|{self.current_friend}|{msg}')
        self.input_edit.clear()
        self.append_text_message('我', msg, is_self=True)

    def open_emoji_dialog(self):
        if self.emoji_dialog is None:
            self.emoji_dialog = EmojiDialog()
            self.emoji_dialog.emoji_selected.connect(self.handle_emoji_selected)
        self.emoji_dialog.show()

    def handle_emoji_selected(self, emoji_id):
        if self.tab_widget.currentWidget() == self.private_tab:
            self.send_emoji(emoji_id)
        else:
            self.send_group_emoji(emoji_id)

    def send_emoji(self, emoji_id):
        if not self.current_friend:
            return
        self.send_message_to_server(f'EMOJI|{self.current_friend}|{emoji_id}')
        self.append_emoji_message('我', emoji_id)

    def send_voice_message(self):
        """发送语音消息"""
        if not self.current_friend:
            QMessageBox.warning(self, '提示', '请先选择好友')
            return
        
        # 语音消息可以发送给离线好友，服务器会保存
        # 不需要检查在线状态
        
        # 打开语音消息录制对话框
        voice_dialog = VoiceMessageDialog(self)
        voice_dialog.voice_message_ready.connect(self.on_voice_message_ready)
        voice_dialog.exec_()

    def on_voice_message_ready(self, audio_data, voice_type):
        """处理录制完成的语音消息"""
        try:
            if not audio_data or len(audio_data) == 0:
                QMessageBox.warning(self, '错误', '录制的音频数据为空')
                return
            
            logging.debug(f"准备发送语音消息: 数据长度={len(audio_data)}, 类型={voice_type}")
            
            # 将音频数据编码为base64以便传输
            import base64
            try:
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                # 移除所有换行符和空白字符，这很重要！
                audio_base64 = audio_base64.replace('\n', '').replace('\r', '').replace(' ', '').replace('\t', '')
                logging.debug(f"音频数据编码成功，base64长度: {len(audio_base64)}")
                
                # 验证base64数据不包含特殊字符
                if '|' in audio_base64 or '\n' in audio_base64:
                    raise Exception("Base64数据包含特殊字符，可能导致传输错误")
                    
            except Exception as encode_error:
                logging.error(f"音频数据编码失败: {encode_error}")
                QMessageBox.warning(self, '发送失败', f'音频数据编码失败: {encode_error}')
                return
            
            # 计算音频时长
            duration = len(audio_data) / (RATE * 2)  # 估算时长
            logging.debug(f"计算音频时长: {duration:.1f}秒")
            
            # 验证参数
            if not self.current_friend:
                QMessageBox.warning(self, '错误', '请先选择好友')
                return
            
            if not voice_type:
                voice_type = "original"
            
            # 发送语音消息到服务器
            try:
                voice_msg = f'VOICE_MSG|{self.current_friend}|{voice_type}|{duration:.1f}|{audio_base64}'
                logging.debug(f"发送语音消息: 目标={self.current_friend}, 消息长度={len(voice_msg)}")
                
                # 确保消息以换行符结尾，这很重要！
                if not voice_msg.endswith('\n'):
                    voice_msg += '\n'
                
                # 验证消息格式
                if voice_msg.count('|') < 4:
                    raise Exception(f"语音消息格式错误，分隔符数量不足: {voice_msg.count('|')}")
                
                # 使用统一的发送方法
                if self.send_message_to_server(voice_msg):
                    logging.debug("语音消息发送成功")
                else:
                    raise Exception("发送语音消息到服务器失败")
                
                # 在本地显示发送的语音消息
                self.append_voice_message('我', audio_data, voice_type, duration, is_self=True)
                
                # 保存发送的语音消息到本地历史记录
                self.save_voice_message_history(self.username, voice_type, duration, audio_base64)
                
            except Exception as send_error:
                logging.error(f"发送语音消息到服务器失败: {send_error}")
                QMessageBox.warning(self, '发送失败', f'发送语音消息失败: {send_error}')
                return
            
        except Exception as e:
            logging.error(f"处理语音消息失败: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, '发送失败', f'处理语音消息失败: {e}')

    def append_voice_message(self, sender, audio_data, voice_type="original", duration=0, is_self=False):
        """在聊天界面添加语音消息"""
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 发送者标签
        name_label = QLabel(f'<b>{sender}:</b>')
        if is_self:
            name_label.setStyleSheet('color:blue;')
        
        # 语音消息播放器
        voice_player = VoiceMessagePlayer(audio_data, voice_type, duration)
        
        layout.addWidget(name_label)
        layout.addWidget(voice_player)
        layout.addStretch()
        
        widget.setLayout(layout)
        
        item = QListWidgetItem()
        self.chat_display.addItem(item)
        self.chat_display.setItemWidget(item, widget)
        item.setSizeHint(widget.sizeHint())
        self.chat_display.scrollToBottom()

    def save_voice_message_history(self, from_user, voice_type, duration, audio_base64):
        """保存语音消息到本地历史记录"""
        try:
            # 创建语音消息存储目录
            voice_dir = os.path.join(os.path.dirname(__file__), 'voice_messages')
            os.makedirs(voice_dir, exist_ok=True)
            
            # 使用字典序排序确保两个用户之间的消息保存在同一个文件中
            users = sorted([self.username, from_user])
            voice_file = os.path.join(voice_dir, f'voice_{users[0]}_{users[1]}.json')
            
            # 读取现有历史记录
            voice_history = []
            if os.path.exists(voice_file):
                try:
                    with open(voice_file, 'r', encoding='utf-8') as f:
                        voice_history = json.load(f)
                except:
                    voice_history = []
            
            # 添加新的语音消息记录
            voice_record = {
                'sender': from_user,
                'voice_type': voice_type,
                'duration': duration,
                'audio_base64': audio_base64,
                'timestamp': time.time()
            }
            voice_history.append(voice_record)
            
            # 保存历史记录
            with open(voice_file, 'w', encoding='utf-8') as f:
                json.dump(voice_history, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logging.error(f"保存语音消息历史失败: {e}")

    def load_voice_message_history(self, friend_name):
        """加载语音消息历史记录"""
        try:
            voice_dir = os.path.join(os.path.dirname(__file__), 'voice_messages')
            users = sorted([self.username, friend_name])
            voice_file = os.path.join(voice_dir, f'voice_{users[0]}_{users[1]}.json')
            
            if not os.path.exists(voice_file):
                return []
            
            with open(voice_file, 'r', encoding='utf-8') as f:
                voice_history = json.load(f)
            
            return voice_history
            
        except Exception as e:
            logging.error(f"加载语音消息历史失败: {e}")
            return []

    def select_group(self, item):
        if self.selecting_group:
            return
        self.selecting_group = True
        try:
            group_info = item.text().split(' ', 1)[0]
            # 统一群组ID格式
            group_info = str(group_info)
            if self.current_group and str(self.current_group) == group_info:
                self.selecting_group = False
                return

            self.current_group = group_info
            # 清除未读标记
            if group_info in self.unread_groups:
                self.unread_groups.remove(group_info)
                self.update_group_list()  # 更新群聊列表显示
            self.tab_widget.setCurrentWidget(self.group_tab)
            self.group_chat_display.clear()
            self.anon_nick = None
            self.group_members_list.clear()
            # 先获取群聊成员，再获取历史记录
            self.send_message_to_server(f'GET_GROUP_MEMBERS|{self.current_group}')
            self.send_message_to_server(f'GET_GROUP_HISTORY|{self.current_group}')
        finally:
            self.selecting_group = False

    def create_group(self):
        group_name, ok = QInputDialog.getText(self, '创建群聊', '输入群聊名称:')
        if ok and group_name:
            self.send_message_to_server(f'CREATE_GROUP|{self.username}|{group_name}')

    def join_group(self):
        group_id, ok = QInputDialog.getText(self, '加入群聊', '输入群聊ID:')
        if ok and group_id:
            self.send_message_to_server(f'JOIN_GROUP|{self.username}|{group_id}')

    def send_group_message(self):
        msg = self.group_input_edit.text().strip()
        if not msg or not self.current_group:
            return
        if self.group_anon_btn.isChecked():
            if not self.anon_nick:
                anon_nick, ok = QInputDialog.getText(self, '匿名昵称', '输入匿名昵称:')
                if not ok or not anon_nick:
                    return
                self.anon_nick = anon_nick
            self.send_message_to_server(f'GROUP_MSG_ANON|{self.current_group}|{self.anon_nick}|{msg}')
            self.append_group_anon_message(self.anon_nick, msg, is_self=True)
        else:
            self.send_message_to_server(f'GROUP_MSG|{self.current_group}|{self.username}|{msg}')
            self.append_group_message(self.username, msg, is_self=True)
        self.group_input_edit.clear()

    def toggle_anon_mode(self):
        if not self.group_anon_btn.isChecked():
            self.anon_nick = None

    def append_group_message(self, sender, msg, is_self=False):
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel(f'<b>{sender}:</b>')
        msg_label = QLabel(msg)
        if is_self:
            name_label.setStyleSheet('color:blue;')
        layout.addWidget(name_label)
        layout.addWidget(msg_label)
        widget.setLayout(layout)
        item = QListWidgetItem()
        self.group_chat_display.addItem(item)
        self.group_chat_display.setItemWidget(item, widget)
        item.setSizeHint(widget.sizeHint())
        self.group_chat_display.scrollToBottom()

    def append_group_anon_message(self, anon_nick, msg, is_self=False):
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel(f'<b>{anon_nick}(匿名):</b>')
        msg_label = QLabel(msg)
        if is_self:
            name_label.setStyleSheet('color:blue;')
        layout.addWidget(name_label)
        layout.addWidget(msg_label)
        widget.setLayout(layout)
        item = QListWidgetItem()
        self.group_chat_display.addItem(item)
        self.group_chat_display.setItemWidget(item, widget)
        item.setSizeHint(widget.sizeHint())
        self.group_chat_display.scrollToBottom()

    def send_group_emoji(self, emoji_id):
        if not self.current_group:
            return
        if self.group_anon_btn.isChecked():
            if not self.anon_nick:
                anon_nick, ok = QInputDialog.getText(self, '匿名昵称', '输入匿名昵称:')
                if not ok or not anon_nick:
                    return
                self.anon_nick = anon_nick
            self.send_message_to_server(f'GROUP_MSG_ANON|{self.current_group}|{self.anon_nick}|[EMOJI]{emoji_id}')
            self.append_group_anon_emoji(self.anon_nick, emoji_id, is_self=True)
        else:
            self.send_message_to_server(f'GROUP_MSG|{self.current_group}|{self.username}|[EMOJI]{emoji_id}')
            self.append_group_emoji(self.username, emoji_id, is_self=True)

    def append_group_emoji(self, sender, emoji_id, is_self=False):
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel(f'<b>{sender}:</b>')
        img_label = QLabel()

        # 尝试从缓存获取表情
        if not self.get_emoji_from_cache(emoji_id, img_label):
            # 路径检查和处理
            path = os.path.join(EMOJI_DIR, emoji_id)
            if not os.path.exists(path):
                print(f"表情文件不存在: {path}")
                # 在图像标签显示错误信息
                img_label.setText(f"[表情: {emoji_id}]")
            elif emoji_id.lower().endswith('.gif'):
                # 使用定时器确保GIF加载完成
                movie = QMovie(path)
                img_label.setMovie(movie)
                movie.setCacheMode(QMovie.CacheAll)
                movie.start()
                # 强制处理事件以确保显示更新
                QApplication.processEvents()
            else:
                # 静态图片加载
                pix = QPixmap(path)
                if pix.isNull():
                    # 如果加载失败，尝试重新加载
                    print(f"表情加载失败，尝试重新加载: {emoji_id}")
                    pix = QPixmap(path)
                img_label.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                # 强制处理事件以确保显示更新
                QApplication.processEvents()

        if is_self:
            name_label.setStyleSheet('color:blue;')
        layout.addWidget(name_label)
        layout.addWidget(img_label)
        widget.setLayout(layout)
        item = QListWidgetItem()
        self.group_chat_display.addItem(item)
        self.group_chat_display.setItemWidget(item, widget)
        item.setSizeHint(widget.sizeHint())
        self.group_chat_display.scrollToBottom()
        # 强制刷新UI
        self.group_chat_display.repaint()

    def append_group_anon_emoji(self, anon_nick, emoji_id, is_self=False):
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel(f'<b>{anon_nick}(匿名):</b>')
        img_label = QLabel()

        # 尝试从缓存获取表情
        if not self.get_emoji_from_cache(emoji_id, img_label):
            # 路径检查和处理
            path = os.path.join(EMOJI_DIR, emoji_id)
            if not os.path.exists(path):
                print(f"表情文件不存在: {path}")
                # 在图像标签显示错误信息
                img_label.setText(f"[表情: {emoji_id}]")
            elif emoji_id.lower().endswith('.gif'):
                # 使用定时器确保GIF加载完成
                movie = QMovie(path)
                img_label.setMovie(movie)
                movie.setCacheMode(QMovie.CacheAll)
                movie.start()
                # 强制处理事件以确保显示更新
                QApplication.processEvents()
            else:
                # 静态图片加载
                pix = QPixmap(path)
                if pix.isNull():
                    # 如果加载失败，尝试重新加载
                    print(f"表情加载失败，尝试重新加载: {emoji_id}")
                    pix = QPixmap(path)
                img_label.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                # 强制处理事件以确保显示更新
                QApplication.processEvents()

        if is_self:
            name_label.setStyleSheet('color:blue;')
        layout.addWidget(name_label)
        layout.addWidget(img_label)
        widget.setLayout(layout)
        item = QListWidgetItem()
        self.group_chat_display.addItem(item)
        self.group_chat_display.setItemWidget(item, widget)
        item.setSizeHint(widget.sizeHint())
        self.group_chat_display.scrollToBottom()
        # 强制刷新UI
        self.group_chat_display.repaint()

    def on_message(self, data):
        try:
            logging.debug(f"处理收到的消息: {data}")
            parts = data.split('|')
            cmd = parts[0]

            # 调试专用 - 添加打印所有消息类型的日志
            print(f"处理消息类型: {cmd}, 完整消息: {data}")

            # 强制下线处理 - 最高优先级
            if cmd == 'FORCE_LOGOUT':
                reason = parts[1] if len(parts) > 1 else "您的账号在其他地方登录"
                logging.warning(f"账号被强制下线: {reason}")
                QMessageBox.warning(self, "强制下线", reason)
                self.close()
                return

            # 移除语音通话相关消息处理

            # 处理其他消息类型
            if cmd == 'PRIVATE_HISTORY':
                try:
                    if parts[1] == 'error':
                        self.append_text_message('[系统]', f'获取历史记录失败: {parts[2]}')
                        return

                    history = parts[1:]
                    print(f"接收到私聊历史记录: {len(history) // 2}条消息")

                    i = 0
                    while i < len(history):
                        if i + 1 >= len(history):
                            print(f"历史记录数据不完整: {history[i:]}")
                            break

                        sender = history[i]
                        msg = history[i + 1]
                        print(f"私聊历史: sender={sender}, msg={msg}")

                        # 显示历史消息
                        if msg.startswith('[EMOJI]'):
                            emoji_id = msg[7:]
                            if sender == self.username:
                                self.append_emoji_message('我', emoji_id)
                            else:
                                self.append_emoji_message(sender, emoji_id)
                        elif msg.startswith('[VOICE:'):
                            # 处理语音消息历史记录
                            try:
                                # 解析语音消息格式: [VOICE:voice_type:duration:audio_base64]
                                voice_content = msg[7:-1]  # 去掉 [VOICE: 和 ]
                                voice_parts = voice_content.split(':', 3)  # 只分割前3个:，剩余的都是audio_base64
                                
                                if len(voice_parts) >= 4:
                                    voice_type = voice_parts[0]
                                    duration_str = voice_parts[1]
                                    # voice_parts[2] 是空的或者其他数据
                                    audio_base64 = voice_parts[3]
                                    
                                    logging.debug(f"解析历史语音消息: type={voice_type}, duration={duration_str}, data_len={len(audio_base64)}")
                                    
                                    try:
                                        duration = float(duration_str)
                                    except ValueError:
                                        logging.warning(f"无效的历史语音消息时长: {duration_str}")
                                        duration = 0.0
                                    
                                    # 解码音频数据
                                    import base64
                                    try:
                                        # 修复base64填充问题
                                        missing_padding = len(audio_base64) % 4
                                        if missing_padding:
                                            audio_base64 += '=' * (4 - missing_padding)
                                        audio_data = base64.b64decode(audio_base64)
                                        logging.debug(f"历史语音消息解码成功，长度: {len(audio_data)} 字节")
                                    except Exception as decode_error:
                                        logging.error(f"历史语音消息base64解码失败: {decode_error}")
                                        # 如果解析失败，显示为文本消息
                                        display_sender = '我' if sender == self.username else sender
                                        is_self = (sender == self.username)
                                        self.append_text_message(display_sender, '[语音消息-解码失败]', is_self)
                                        continue
                                    
                                    # 验证音频数据
                                    if len(audio_data) == 0:
                                        logging.warning("历史语音消息数据为空")
                                        display_sender = '我' if sender == self.username else sender
                                        is_self = (sender == self.username)
                                        self.append_text_message(display_sender, '[语音消息-数据为空]', is_self)
                                        continue
                                    
                                    # 显示语音消息
                                    display_sender = '我' if sender == self.username else sender
                                    is_self = (sender == self.username)
                                    self.append_voice_message(display_sender, audio_data, voice_type, duration, is_self)
                                else:
                                    logging.error(f"语音消息格式错误，参数不足: {msg}")
                                    # 如果解析失败，显示为文本消息
                                    display_sender = '我' if sender == self.username else sender
                                    is_self = (sender == self.username)
                                    self.append_text_message(display_sender, '[语音消息-格式错误]', is_self)
                            except Exception as e:
                                logging.error(f"处理历史语音消息失败: {e}")
                                import traceback
                                traceback.print_exc()
                                # 如果解析失败，显示为文本消息
                                display_sender = '我' if sender == self.username else sender
                                is_self = (sender == self.username)
                                self.append_text_message(display_sender, '[语音消息-处理失败]', is_self)
                        else:
                            if sender == self.username:
                                self.append_text_message('我', msg, is_self=True)
                            else:
                                self.append_text_message(sender, msg)
                        i += 2
                except Exception as e:
                    print(f"处理私聊历史记录出错: {e}")
                    self.append_text_message('[系统]', '处理历史记录出错')
            elif cmd == 'MSG':
                from_user, msg = parts[1], '|'.join(parts[2:])
                if self.tab_widget.currentWidget() == self.private_tab and from_user == self.current_friend:
                    self.append_text_message(from_user, msg)
            elif cmd == 'EMOJI':
                from_user, emoji_id = parts[1], parts[2]
                if self.tab_widget.currentWidget() == self.private_tab and from_user == self.current_friend:
                    self.append_emoji_message(from_user, emoji_id)
            elif cmd == 'VOICE_MSG':
                # VOICE_MSG|from_user|voice_type|duration|audio_base64
                try:
                    # 使用更安全的方式解析消息，避免base64数据中的|字符干扰
                    msg_parts = data.split('|', 4)  # 只分割前4个|，剩余的都是audio_base64
                    if len(msg_parts) < 5:
                        logging.error(f"语音消息格式错误: 参数不足，收到 {len(msg_parts)} 个参数")
                        self.append_text_message('[系统]', '收到格式错误的语音消息')
                        return
                    
                    from_user = msg_parts[1]
                    voice_type = msg_parts[2]
                    duration_str = msg_parts[3]
                    audio_base64 = msg_parts[4]
                    
                    logging.debug(f"收到语音消息: from={from_user}, type={voice_type}, duration={duration_str}, data_len={len(audio_base64)}")
                    
                    # 验证参数
                    if not from_user or not voice_type or not duration_str or not audio_base64:
                        logging.error("语音消息参数无效")
                        self.append_text_message('[系统]', '收到无效的语音消息')
                        return
                    
                    try:
                        duration = float(duration_str)
                    except ValueError:
                        logging.error(f"无效的时长参数: {duration_str}")
                        duration = 0.0
                    
                    # 解码音频数据
                    import base64
                    try:
                        # 修复base64填充问题
                        missing_padding = len(audio_base64) % 4
                        if missing_padding:
                            audio_base64 += '=' * (4 - missing_padding)
                        audio_data = base64.b64decode(audio_base64)
                        logging.debug(f"音频数据解码成功，长度: {len(audio_data)} 字节")
                    except Exception as decode_error:
                        logging.error(f"base64解码失败: {decode_error}")
                        self.append_text_message('[系统]', f'语音消息解码失败: {decode_error}')
                        return
                    
                    # 验证音频数据
                    if len(audio_data) == 0:
                        logging.error("音频数据为空")
                        self.append_text_message('[系统]', '收到空的语音消息')
                        return
                    
                    # 只在当前私聊界面显示
                    if self.tab_widget.currentWidget() == self.private_tab and from_user == self.current_friend:
                        self.append_voice_message(from_user, audio_data, voice_type, duration)
                    
                    # 保存语音消息历史
                    self.save_voice_message_history(from_user, voice_type, duration, audio_base64)
                    
                except Exception as e:
                    logging.error(f"处理语音消息失败: {e}")
                    import traceback
                    traceback.print_exc()
                    self.append_text_message('[系统]', f'处理语音消息失败: {str(e)}')
            elif cmd == 'VOICE_MSG_SENT':
                # 语音消息发送确认
                try:
                    to_user = parts[1] if len(parts) > 1 else ''
                    logging.debug(f"语音消息发送成功: 发送给 {to_user}")
                    # 可以在这里添加发送成功的UI反馈，比如显示一个小提示
                    if to_user == self.current_friend:
                        # 可以在聊天界面显示发送成功的提示
                        pass
                except Exception as e:
                    logging.error(f"处理语音消息发送确认失败: {e}")
            # 移除所有语音通话相关的消息处理代码
            elif cmd == 'FRIEND_LIST':
                self.friends = []
                self.friend_list.clear()
                self.friend_status = {}
                for f in parts[1:]:
                    if f and ':' in f:
                        name, status = f.split(':')
                        self.friends.append(name)
                        self.friend_status[name] = status
                        item = QListWidgetItem(f'{name} ({"在线" if status == "online" else "离线"})')
                        if status == 'online':
                            item.setForeground(QColor('green'))
                        else:
                            item.setForeground(QColor('red'))
                        self.friend_list.addItem(item)
            elif cmd == 'GROUP_LIST':
                self.group_list.clear()
                for g in parts[1:]:
                    if g and ':' in g:
                        gid, gname = g.split(':', 1)
                        display_text = f'{gid} {gname}'
                        if gid in self.unread_groups:
                            display_text += ' [有新消息]'
                        item = QListWidgetItem(display_text)
                        if gid in self.unread_groups:
                            item.setForeground(QColor('blue'))
                        self.group_list.addItem(item)
            elif cmd == 'GROUP_MEMBERS':
                self.group_members_list.clear()
                for m in parts[1:]:
                    if m:
                        self.group_members_list.addItem(m)
            elif cmd == 'GROUP_MSG':
                try:
                    # 确保正确解析群聊消息
                    if len(parts) < 4:
                        print(f"群聊消息格式错误: {data}")
                        return

                    group_id, from_user, msg = parts[1], parts[2], '|'.join(parts[3:])
                    print(f"接收到群聊消息: group_id={group_id}, from_user={from_user}, msg={msg}")

                    # 统一群组ID格式
                    group_id_str = str(group_id)
                    current_group_str = str(self.current_group) if self.current_group else ""

                    # 收到消息意味着用户在线，更新好友状态
                    if from_user in self.friends:
                        self.update_friend_status(from_user, True)

                    # 不处理自己发送的消息，因为发送时已经显示过了
                    if from_user == self.username:
                        return

                    # 无论当前是否在该群聊界面，都保存并处理消息
                    if current_group_str == group_id_str and self.tab_widget.currentWidget() == self.group_tab:
                        # 用户当前正在查看该群聊，显示消息
                        if msg.startswith('[EMOJI]'):
                            emoji_id = msg[7:]
                            self.append_group_emoji(from_user, emoji_id)
                        else:
                            self.append_group_message(from_user, msg)
                    else:
                        # 用户未查看该群聊，添加未读标记
                        self.unread_groups.add(group_id)
                        self.update_group_list()
                except Exception as e:
                    print(f"处理群聊消息出错: {e}, 消息内容: {data}")
            elif cmd == 'GROUP_MSG_ANON':
                try:
                    # 确保正确解析匿名群聊消息
                    if len(parts) < 4:
                        print(f"匿名群聊消息格式错误: {data}")
                        return

                    group_id, anon_nick, msg = parts[1], parts[2], '|'.join(parts[3:])
                    print(f"接收到匿名群聊消息: group_id={group_id}, anon_nick={anon_nick}, msg={msg}")

                    # 统一群组ID格式
                    group_id_str = str(group_id)
                    current_group_str = str(self.current_group) if self.current_group else ""

                    # 不处理自己发送的匿名消息，因为发送时已经显示过了
                    if self.anon_nick and anon_nick == self.anon_nick:
                        return

                    # 无论当前是否在该群聊界面，都保存并处理消息
                    if current_group_str == group_id_str and self.tab_widget.currentWidget() == self.group_tab:
                        # 用户当前正在查看该群聊，显示消息
                        if msg.startswith('[EMOJI]'):
                            emoji_id = msg[7:]
                            self.append_group_anon_emoji(anon_nick, emoji_id)
                        else:
                            self.append_group_anon_message(anon_nick, msg)
                    else:
                        # 用户未查看该群聊，添加未读标记
                        self.unread_groups.add(group_id)
                        self.update_group_list()
                except Exception as e:
                    print(f"处理匿名群聊消息出错: {e}, 消息内容: {data}")
            elif cmd == 'GROUP_HISTORY':
                try:
                    self.group_chat_display.clear()
                    history = parts[1:]
                    print(f"接收到群聊历史记录: {len(history) // 3}条消息")

                    i = 0
                    while i < len(history):
                        if i + 2 >= len(history):
                            print(f"历史记录数据不完整: {history[i:]}")
                            break

                        if history[i] == 'user':
                            sender = history[i + 1]
                            msg = history[i + 2]
                            print(f"历史记录: user={sender}, msg={msg}")
                            if msg.startswith('[EMOJI]'):
                                emoji_id = msg[7:]
                                self.append_group_emoji(sender, emoji_id)
                            else:
                                self.append_group_message(sender, msg)
                            i += 3
                        elif history[i] == 'anon':
                            anon_nick = history[i + 1]
                            msg = history[i + 2]
                            print(f"历史记录: anon={anon_nick}, msg={msg}")
                            if msg.startswith('[EMOJI]'):
                                emoji_id = msg[7:]
                                self.append_group_anon_emoji(anon_nick, emoji_id)
                            else:
                                self.append_group_anon_message(anon_nick, msg)
                            i += 3
                        else:
                            print(f"未知的历史记录类型: {history[i]}")
                            i += 1
                except Exception as e:
                    print(f"处理群聊历史记录出错: {e}, 历史记录数据: {history}")
            elif cmd == 'ADD_FRIEND_RESULT':
                if parts[1] == 'OK':
                    QMessageBox.information(self, '添加好友', parts[2])
                    self.get_friends()
                else:
                    QMessageBox.warning(self, '添加好友失败', parts[2])
            elif cmd == 'DEL_FRIEND_RESULT':
                if parts[1] == 'OK':
                    QMessageBox.information(self, '删除好友', parts[2])
                    self.get_friends()
                    self.current_friend = None
                    self.chat_display.clear()
                else:
                    QMessageBox.warning(self, '删除好友失败', parts[2])
            elif cmd == 'ERROR':
                self.append_text_message('[错误]', parts[1])
            elif cmd == 'FRIEND_ONLINE':
                username = parts[1]
                self.update_friend_status(username, True)
            elif cmd == 'FRIEND_OFFLINE':
                username = parts[1]
                self.update_friend_status(username, False)
            elif cmd == 'CREATE_GROUP_RESULT':
                if parts[1] == 'OK':
                    group_id = parts[3] if len(parts) > 3 else ''
                    QMessageBox.information(self, '创建群聊', f'{parts[2]}\n群ID: {group_id}')
                    self.get_groups()
                else:
                    QMessageBox.warning(self, '创建群聊失败', parts[2])
            elif cmd == 'JOIN_GROUP_RESULT':
                if parts[1] == 'OK':
                    group_id = parts[3] if len(parts) > 3 else ''
                    QMessageBox.information(self, '加入群聊', f'{parts[2]}\n群ID: {group_id}')
                    self.get_groups()
                else:
                    QMessageBox.warning(self, '加入群聊失败', parts[2])
            elif cmd == 'FILE_LIST':
                # FILE_LIST|file1|file2|...
                self.update_private_file_list(parts[1:])
            elif cmd == 'FILE_DATA':
                # FILE_DATA|filename|filesize
                fname = parts[1]
                filesize = int(parts[2])
                # 接收文件数据
                filedata = b''
                while len(filedata) < filesize:
                    chunk = self.sock.recv(min(4096, filesize - len(filedata)))
                    if not chunk:
                        break
                    filedata += chunk

                # 确保FILES_DIR存在
                os.makedirs(FILES_DIR, exist_ok=True)

                # 保存文件到FILES_DIR目录
                save_path = os.path.join(FILES_DIR, fname)
                with open(save_path, 'wb') as f:
                    f.write(filedata)
                QMessageBox.information(self, '下载完成', f'文件已保存到: {save_path}')
        except Exception as e:
            logging.error(f"处理消息时出错: {e}, 消息内容: {data}", exc_info=True)

    def update_friend_status(self, username, online):
        # 更新好友列表项颜色和状态
        for i in range(self.friend_list.count()):
            item = self.friend_list.item(i)
            if item.text().startswith(username + ' '):
                status_str = '在线' if online else '离线'
                item.setText(f'{username} ({status_str})')
                item.setForeground(QColor('green' if online else 'red'))
                break
        if hasattr(self, 'friend_status'):
            self.friend_status[username] = 'online' if online else 'offline'

    def update_group_list(self):
        """更新群聊列表，包括未读消息标记"""
        current_items = []
        for i in range(self.group_list.count()):
            current_items.append(self.group_list.item(i).text())

        self.group_list.clear()
        for item in current_items:
            group_id = item.split(' ', 1)[0]
            display_text = item
            if group_id in self.unread_groups:
                display_text = f"{item} [有新消息]"
            list_item = QListWidgetItem(display_text)
            if group_id in self.unread_groups:
                list_item.setForeground(QColor('blue'))
            self.group_list.addItem(list_item)

    def on_connection_lost(self):
        QMessageBox.critical(self, '错误', '服务器连接断开，请重新登录')
        self.close()  # 关闭当前窗口
        # 重新显示登录窗口
        self.login_window = LoginWindow()
        self.login_window.show()

    def closeEvent(self, event):
        try:
            # 移除语音通话相关的清理代码

            # 尝试发送登出消息，但不等待响应
            try:
                self.send_message_to_server('LOGOUT|')
            except:
                pass

            # 停止客户端线程
            self.client_thread.stop()

            # 关闭socket连接
            try:
                self.sock.close()
            except:
                pass

            # 接受关闭事件
            event.accept()

            # 只有在用户主动关闭窗口时才退出程序
            if event.spontaneous():
                QApplication.quit()

        except Exception as e:
            print(f"关闭窗口时出错: {e}")
            event.accept()
            # 只有在用户主动关闭窗口时才退出程序
            if event.spontaneous():
                QApplication.quit()

    def initial_refresh(self):
        """登录后初始化刷新好友和群聊列表"""
        try:
            # 使用定时器延迟执行，避免阻塞主窗口初始化
            QTimer.singleShot(100, self.delayed_refresh)
        except Exception as e:
            logging.error(f"初始化刷新出错: {e}")
    
    def delayed_refresh(self):
        """延迟执行的刷新操作"""
        try:
            logging.debug("开始延迟刷新好友和群组列表")
            self.get_friends()
            self.get_groups()
            logging.debug("延迟刷新完成")
        except Exception as e:
            logging.error(f"延迟刷新出错: {e}")

    # 移除所有语音通话相关的方法

    def switch_background(self):
        """切换聊天背景图片"""
        bg_files = [f for f in os.listdir(BG_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))]
        if not bg_files:
            QMessageBox.information(self, '提示', '请在backgrounds文件夹中添加背景图片')
            return
        self.current_bg_index = (getattr(self, 'current_bg_index', 0) + 1) % len(bg_files)
        bg_path = os.path.join(BG_DIR, bg_files[self.current_bg_index])
        bg_path_url = bg_path.replace("\\", "/")
        self.setStyleSheet(
            f'QWidget {{ background-image: url("{bg_path_url}"); background-repeat: no-repeat; background-position: center; }}')

    def change_resolution(self):
        """弹窗选择分辨率并调整窗口大小"""
        resolutions = ['800x600', '1024x768', '1280x800', '1366x768', '1440x900', '1600x900', '1920x1080']
        res, ok = QInputDialog.getItem(self, '选择分辨率', '分辨率:', resolutions, 0, False)
        if ok and res:
            w, h = map(int, res.split('x'))
            self.resize(w, h)
            center_window(self)

    class FileTransfer:
        """简化的文件传输类，使用专用socket连接"""

        @staticmethod
        def upload_file(server_host, server_port, username, to_user, file_path, progress_callback=None):
            """上传文件到服务器

            Args:
                server_host: 服务器主机名
                server_port: 文件传输服务器端口
                username: 发送者用户名
                to_user: 接收者用户名
                file_path: 本地文件路径
                progress_callback: 进度回调函数，接收参数(percent)

            Returns:
                (success, message): 成功状态和消息
            """
            try:
                # 创建专用socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(30)  # 30秒超时
                sock.connect((server_host, server_port))

                # 获取文件信息
                file_size = os.path.getsize(file_path)
                file_name = os.path.basename(file_path)

                # 发送认证和请求头
                auth_msg = f'UPLOAD|{username}|{to_user}|{file_name}|{file_size}'
                sock.send(auth_msg.encode('utf-8'))

                # 等待服务器准备就绪
                response = sock.recv(1024).decode('utf-8')
                if not response.startswith('READY'):
                    if response.startswith('ERROR'):
                        error_msg = response.split('|', 1)[1] if '|' in response else "Unknown error"
                        return False, f"服务器错误: {error_msg}"
                    return False, f"服务器响应错误: {response}"

                # 从响应中获取服务器可能修改过的文件名
                if '|' in response:
                    file_name = response.split('|', 1)[1]

                # 开始上传文件
                sent = 0
                last_progress = 0
                with open(file_path, 'rb') as f:
                    while sent < file_size:
                        # 读取并发送数据块
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        sock.sendall(chunk)
                        sent += len(chunk)

                        # 更新进度
                        progress = min(100, int(sent * 100 / file_size))
                        if progress != last_progress:
                            if progress_callback:
                                progress_callback(progress)
                            last_progress = progress

                        # 检查服务器进度更新
                        if sent % (1024 * 1024) == 0 or sent == file_size:  # 每1MB或完成时
                            try:
                                sock.settimeout(2)  # 短超时
                                prog_update = sock.recv(1024).decode('utf-8')
                                if prog_update.startswith('PROGRESS'):
                                    server_progress = int(prog_update.split('|')[1])
                                    logging.debug(f"服务器确认进度: {server_progress}%")
                                sock.settimeout(30)  # 恢复长超时
                            except socket.timeout:
                                # 超时不中断传输
                                sock.settimeout(30)
                            except Exception as e:
                                logging.warning(f"接收服务器进度更新出错: {e}")
                                # 继续传输

                # 等待最终确认
                sock.settimeout(10)
                final_response = sock.recv(1024).decode('utf-8')
                if final_response == 'SUCCESS':
                    return True, f"文件 {file_name} 已成功上传"
                else:
                    return False, f"上传失败: {final_response}"

            except socket.timeout:
                return False, "连接服务器超时"
            except ConnectionRefusedError:
                return False, "服务器拒绝连接，请确认服务器正在运行"
            except Exception as e:
                return False, f"上传出错: {str(e)}"
            finally:
                try:
                    sock.close()
                except:
                    pass

        @staticmethod
        def download_file(server_host, server_port, username, from_user, file_name, save_path, progress_callback=None):
            """从服务器下载文件

            Args:
                server_host: 服务器主机名
                server_port: 文件传输服务器端口
                username: 下载者用户名
                from_user: 文件所有者用户名
                file_name: 要下载的文件名
                save_path: 本地保存路径
                progress_callback: 进度回调函数，接收参数(percent)

            Returns:
                (success, message): 成功状态和消息
            """
            temp_path = save_path + ".tmp"
            try:
                # 创建专用socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(30)  # 30秒超时
                sock.connect((server_host, server_port))

                # 发送认证和请求头
                auth_msg = f'DOWNLOAD|{username}|{from_user}|{file_name}'
                sock.send(auth_msg.encode('utf-8'))

                # 等待服务器准备就绪
                response = sock.recv(1024).decode('utf-8')
                if not response.startswith('READY'):
                    if response.startswith('ERROR'):
                        error_msg = response.split('|', 1)[1] if '|' in response else "Unknown error"
                        return False, f"服务器错误: {error_msg}"
                    return False, f"服务器响应错误: {response}"

                # 获取文件大小
                file_size = int(response.split('|')[1])

                # 开始下载文件
                received = 0
                last_progress = 0
                with open(temp_path, 'wb') as f:
                    while received < file_size:
                        # 计算剩余大小并接收数据
                        chunk_size = min(8192, file_size - received)
                        chunk = sock.recv(chunk_size)

                        if not chunk:
                            # 如果连接关闭但已收到接近完整的文件，尝试继续
                            if received >= file_size * 0.99:  # 如果收到了99%以上
                                logging.warning(f"连接关闭，但已接收足够数据: {received}/{file_size}")
                                break
                            else:
                                raise Exception("连接过早关闭，文件不完整")

                        f.write(chunk)
                        received += len(chunk)

                        # 更新进度
                        progress = min(100, int(received * 100 / file_size))
                        if progress != last_progress:
                            if progress_callback:
                                progress_callback(progress)
                            last_progress = progress

                        # 定期发送确认
                        if received % (1024 * 1024) == 0 or received == file_size:  # 每1MB或完成时
                            try:
                                sock.send(f'ACK|{progress}'.encode('utf-8'))
                            except:
                                # 发送确认失败不中断下载
                                pass

                # 验证文件大小
                if os.path.getsize(temp_path) != file_size:
                    raise Exception(f"文件大小不匹配: 预期{file_size}字节，实际接收{os.path.getsize(temp_path)}字节")

                # 重命名文件
                if os.path.exists(save_path):
                    os.remove(save_path)
                os.rename(temp_path, save_path)

                return True, f"文件已保存到: {save_path}"

            except socket.timeout:
                return False, "下载超时"
            except ConnectionRefusedError:
                return False, "服务器拒绝连接，请确认服务器正在运行"
            except Exception as e:
                return False, f"下载出错: {str(e)}"
            finally:
                try:
                    sock.close()
                except:
                    pass
                # 清理临时文件
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass

    def upload_private_file(self):
        if not self.current_friend:
            QMessageBox.warning(self, '提示', '请先选择好友')
            return

        file_path, _ = QFileDialog.getOpenFileName(self, '选择要上传的文件', '', 'All Files (*)')
        if not file_path:
            return

        progress = None
        try:
            # 创建进度对话框
            progress = QProgressDialog("准备上传文件...", "取消", 0, 100, self)
            progress.setWindowTitle("上传进度")
            progress.setWindowModality(Qt.WindowModal)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.show()

            # 准备上传请求
            self.send_message_to_server(
                f'FILE_UPLOAD_START|{self.username}|{self.current_friend}|{os.path.basename(file_path)}|{os.path.getsize(file_path)}|1')

            # 等待服务器响应 - 应该是重定向到文件传输端口
            response = self.sock.recv(1024).decode('utf-8')
            if not response.startswith('USE_FILE_PORT'):
                if response.startswith('ERROR'):
                    error_msg = response.split('|', 1)[1] if '|' in response else "未知错误"
                    raise Exception(f"服务器错误: {error_msg}")
                else:
                    raise Exception(f"服务器响应错误: {response}")

            # 解析文件传输端口
            parts = response.split('|')
            if len(parts) < 3:
                raise Exception("无效的重定向响应")

            file_port = int(parts[1])
            logging.info(f"服务器指示使用专用文件端口: {file_port}")

            # 定义进度回调
            def update_progress(percent):
                if progress and not progress.wasCanceled():
                    progress.setValue(percent)
                    progress.setLabelText(f"正在上传: {os.path.basename(file_path)}\n进度: {percent}%")
                    QApplication.processEvents()

            # 使用专用连接上传文件
            success, message = self.FileTransfer.upload_file(
                SERVER_HOST, file_port, self.username, self.current_friend,
                file_path, update_progress
            )

            if success:
                QMessageBox.information(self, '上传成功', message)
                # 刷新文件列表
                self.get_private_file_list()
            else:
                raise Exception(message)

        except Exception as e:
            logging.error(f"文件上传失败: {e}")
            QMessageBox.warning(self, '上传失败', f'文件上传失败: {str(e)}')
            # 无论如何都尝试刷新文件列表
            try:
                self.get_private_file_list()
            except:
                pass
        finally:
            if progress is not None:
                progress.close()

    def download_private_file(self, item):
        if not item:
            return

        fname = item.text()
        progress = None

        try:
            # 让用户选择保存位置
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                '选择保存位置',
                os.path.join(FILES_DIR, fname),
                'All Files (*)'
            )

            if not save_path:
                return

            # 创建进度对话框
            progress = QProgressDialog("准备下载文件...", "取消", 0, 100, self)
            progress.setWindowTitle("下载进度")
            progress.setWindowModality(Qt.WindowModal)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.show()

            # 请求下载文件
            self.send_message_to_server(f'FILE_DOWNLOAD_START|{self.username}|{self.current_friend}|{fname}')

            # 等待服务器响应
            response = self.sock.recv(1024).decode('utf-8')
            if not response.startswith('USE_FILE_PORT'):
                if response.startswith('ERROR'):
                    error_msg = response.split('|', 1)[1] if '|' in response else "未知错误"
                    raise Exception(f"服务器错误: {error_msg}")
                else:
                    raise Exception(f"服务器响应错误: {response}")

            # 解析文件传输端口
            parts = response.split('|')
            if len(parts) < 3:
                raise Exception("无效的重定向响应")

            file_port = int(parts[1])
            logging.info(f"服务器指示使用专用文件端口: {file_port}")

            # 定义进度回调
            def update_progress(percent):
                if progress and not progress.wasCanceled():
                    progress.setValue(percent)
                    progress.setLabelText(f"正在下载: {fname}\n进度: {percent}%")
                    QApplication.processEvents()

            # 使用专用连接下载文件
            success, message = self.FileTransfer.download_file(
                SERVER_HOST, file_port, self.username, self.current_friend,
                fname, save_path, update_progress
            )

            if success:
                QMessageBox.information(self, '下载完成', message)
            else:
                raise Exception(message)

        except Exception as e:
            logging.error(f"文件下载失败: {e}")
            QMessageBox.warning(self, '下载失败', f'下载文件失败: {str(e)}')
        finally:
            if progress is not None:
                progress.close()

    def get_private_file_list(self):
        if not self.current_friend:
            return
        try:
            self.send_message_to_server(f'FILE_LIST|{self.username}|{self.current_friend}')
        except Exception as e:
            QMessageBox.warning(self, '网络错误', f'获取文件列表失败: {e}')

    def update_private_file_list(self, file_list):
        self.private_files = file_list
        self.file_list.clear()
        for fname in file_list:
            self.file_list.addItem(fname)


# 移除CallNotificationWindow类


FILES_DIR = os.path.join(os.path.dirname(__file__), 'files')
os.makedirs(FILES_DIR, exist_ok=True)

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # 检查网络配置
    if not check_network_config():
        sys.exit(1)

    win = LoginWindow()
    win.show()
    sys.exit(app.exec_()) 