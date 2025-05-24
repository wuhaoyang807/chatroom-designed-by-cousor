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
import opuslib  # 添加Opus编解码库
import numpy as np  # 添加numpy用于音频处理

# 配置日志
log_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f'client_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

# 服务器配置
SERVER_HOST = '127.0.0.1'  # 默认本地地址
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
CHUNK = 960  # Opus处理帧大小，使用Opus推荐值
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 48000  # Opus推荐采样率

# Opus编解码器配置
OPUS_FRAME_SIZE = CHUNK  # 每帧样本数
OPUS_SAMPLE_RATE = RATE
OPUS_BITRATE = 32000  # 比特率，质量和带宽的平衡
OPUS_APPLICATION = opuslib.APPLICATION_VOIP  # 为语音通话优化


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


# Opus编解码器类
class OpusCodec:
    """处理Opus音频编解码的类"""

    def __init__(self, sample_rate=OPUS_SAMPLE_RATE, channels=CHANNELS, application=OPUS_APPLICATION):
        self.sample_rate = sample_rate
        self.channels = channels
        self.application = application
        self.encoder = None
        self.decoder = None
        self.frame_size = OPUS_FRAME_SIZE
        self.init_codec()
        logging.debug(f"Opus编解码器初始化: 采样率={sample_rate}, 通道数={channels}")

    def init_codec(self):
        try:
            # 初始化编码器
            self.encoder = opuslib.Encoder(self.sample_rate, self.channels, self.application)
            self.encoder.bitrate = OPUS_BITRATE

            # 初始化解码器
            self.decoder = opuslib.Decoder(self.sample_rate, self.channels)
            logging.debug("Opus编解码器初始化成功")
        except Exception as e:
            logging.error(f"Opus编解码器初始化失败: {e}")
            raise

    def encode(self, pcm_data):
        """将PCM音频数据编码为Opus格式"""
        try:
            # 确保输入数据是正确的长度
            if len(pcm_data) != self.frame_size * self.channels * 2:  # 2字节每样本 (16位)
                logging.warning(f"PCM数据长度不匹配: 实际={len(pcm_data)}, 期望={self.frame_size * self.channels * 2}")
                # 如果需要，进行长度调整
                if len(pcm_data) < self.frame_size * self.channels * 2:
                    # 如果数据太少，用零填充
                    pcm_data = pcm_data + b'\x00' * (self.frame_size * self.channels * 2 - len(pcm_data))
                else:
                    # 如果数据太多，截断
                    pcm_data = pcm_data[:self.frame_size * self.channels * 2]

            # 调用Opus编码器
            encoded_data = self.encoder.encode(pcm_data, self.frame_size)
            return encoded_data
        except Exception as e:
            logging.error(f"Opus编码错误: {e}")
            return None

    def decode(self, opus_data):
        """将Opus格式音频数据解码为PCM"""
        try:
            decoded_data = self.decoder.decode(opus_data, self.frame_size)
            return decoded_data
        except Exception as e:
            logging.error(f"Opus解码错误: {e}")
            return None


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
        self.send_count = 0  # 添加计数器用于统计发送的数据包数量
        self.recv_count = 0  # 添加计数器用于统计接收的数据包数量

        # 创建 Opus 编解码器
        try:
            self.opus_codec = OpusCodec()
            logging.debug("Opus编解码器创建成功")
        except Exception as e:
            logging.error(f"Opus编解码器创建失败: {e}")
            self.opus_codec = None

        logging.debug(f"UDP音频线程绑定到端口: {self.local_port}")

    def run(self):
        logging.debug(f"UDP音频接收线程开始运行，端口: {self.local_port}")
        while self.running and not self.error_occurred:
            try:
                data, addr = self.udp_socket.recvfrom(65536)
                if data and len(data) > 1:
                    try:
                        # 解析头部
                        header_len = data[0]
                        if len(data) > header_len + 1:
                            # 提取头部和音频数据
                            header_bytes = data[1:header_len + 1]
                            encoded_audio = data[header_len + 1:]

                            try:
                                header = header_bytes.decode('utf-8')
                                parts = header.split('|')
                                if len(parts) == 2:
                                    sender, receiver = parts
                                    self.recv_count += 1

                                    # 每收到10个包记录一次日志
                                    if self.recv_count % 10 == 0:
                                        logging.debug(
                                            f"收到UDP音频数据: 包 #{self.recv_count}, {len(encoded_audio)} 字节，来自: {addr}, 头部: {header}")

                                    if encoded_audio and len(encoded_audio) > 0:
                                        # 使用Opus解码器解码音频数据
                                        if self.opus_codec:
                                            try:
                                                # 使用Opus解码器解码数据
                                                decoded_audio = self.opus_codec.decode(encoded_audio)
                                                if decoded_audio:
                                                    self.audio_received.emit(decoded_audio)
                                                else:
                                                    logging.warning("音频解码失败，返回空数据")
                                            except Exception as e:
                                                logging.error(f"Opus解码错误: {e}")
                                                # 如果解码失败，尝试直接使用原始数据
                                                self.audio_received.emit(encoded_audio)
                                        else:
                                            # 如果没有Opus编解码器，直接发送原始数据
                                            self.audio_received.emit(encoded_audio)
                                else:
                                    logging.warning(f"收到无效头部格式: {header}")
                            except UnicodeDecodeError:
                                logging.error(f"无法解码头部: {header_bytes}")
                        else:
                            logging.warning(f"数据包头部不完整: 头部长度={header_len}, 数据长度={len(data)}")
                    except Exception as e:
                        logging.error(f"处理UDP数据包错误: {e}")
            except socket.timeout:
                continue
            except Exception as e:
                logging.error(f"UDP接收错误: {e}")
                time.sleep(0.1)

    def send_audio(self, audio_data, target_addr, sender, receiver):
        try:
            # 验证参数
            if not audio_data or len(audio_data) == 0:
                logging.warning("无效的音频数据")
                return

            if not target_addr or target_addr[0] is None or target_addr[1] is None:
                logging.warning(f"无效的目标地址: {target_addr}")
                return

            # 使用Opus编码器对音频数据进行编码
            encoded_audio = audio_data
            if self.opus_codec:
                try:
                    # 使用Opus编码器编码数据
                    encoded_data = self.opus_codec.encode(audio_data)
                    if encoded_data:
                        encoded_audio = encoded_data
                        # 每发送100个包记录一次编码效率
                        if self.send_count % 100 == 0:
                            compression_ratio = len(audio_data) / len(encoded_audio) if len(encoded_audio) > 0 else 0
                            logging.debug(
                                f"Opus编码成功: 原始大小={len(audio_data)}字节, 编码后={len(encoded_audio)}字节, 压缩比={compression_ratio:.2f}")
                except Exception as e:
                    logging.error(f"Opus编码错误: {e}")
                    # 如果编码失败，继续使用原始数据
                    encoded_audio = audio_data

            # 构建头部: sender|receiver
            header = f"{sender}|{receiver}"
            header_bytes = header.encode('utf-8')
            header_len = len(header_bytes)

            # 构建完整数据包: [头部长度(1字节)][头部][音频数据]
            packet = bytearray([header_len]) + header_bytes + encoded_audio

            self.udp_socket.sendto(packet, target_addr)
            self.send_count += 1

            # 每发送50个数据包记录一次日志
            if self.send_count % 50 == 0:
                logging.debug(
                    f"发送UDP音频数据: 包 #{self.send_count}, 原始={len(audio_data)}字节, 发送={len(encoded_audio)}字节, 到: {target_addr}, 头部: {header}")

        except Exception as e:
            logging.error(f"发送音频数据失败: {e}")
            self.error_occurred = True

    def stop(self):
        logging.debug(f"停止UDP音频线程，发送: {self.send_count} 包，接收: {self.recv_count} 包")
        self.running = False
        try:
            self.udp_socket.close()
        except Exception as e:
            logging.error(f"关闭UDP套接字错误: {e}")
        self.quit()
        self.wait()


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
        logging.debug(f"初始化音频录制器: input_device_index={input_device_index}")

    def run(self):
        try:
            # 初始化音频设备
            self.audio = pyaudio.PyAudio()

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

            # 记录包计数
            packet_count = 0

            # 持续录制和发送音频
            while self.running and not self.error_occurred:
                if self.stream and self.stream.is_active():
                    try:
                        # 使用exception_on_overflow=False避免因缓冲区溢出而丢失数据
                        audio_data = self.stream.read(CHUNK, exception_on_overflow=False)
                        if audio_data and len(audio_data) > 0:
                            packet_count += 1
                            # 每录制50个包记录一次日志
                            if packet_count % 50 == 0:
                                logging.debug(f"录制到音频数据: 包 #{packet_count}, {len(audio_data)} 字节")
                            self.udp_thread.send_audio(audio_data, self.target_addr, self.sender, self.receiver)
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
        logging.debug(f"初始化音频播放器: output_device_index={output_device_index}")

    def run(self):
        try:
            # 初始化音频设备
            self.audio = pyaudio.PyAudio()

            # 获取输出设备信息
            device_info = self.audio.get_device_info_by_index(self.output_device_index)
            logging.debug(f"使用输出设备: {device_info['name']}")
            logging.debug(f"设备信息: {device_info}")

            # 打开音频流，使用较小的缓冲区以减少延迟
            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                frames_per_buffer=CHUNK,
                output_device_index=self.output_device_index,
                stream_callback=None,
                start=True  # 确保流立即启动
            )

            logging.debug("开始音频播放...")

            # 记录播放的包数量
            played_count = 0
            empty_queue_count = 0

            # 持续从队列中获取和播放音频
            while self.running and not self.error_occurred:
                if self.stream and self.stream.is_active():
                    try:
                        audio_data = None
                        with self.queue_lock:
                            if self.audio_queue:
                                audio_data = self.audio_queue.pop(0)
                                empty_queue_count = 0  # 重置空队列计数
                            else:
                                empty_queue_count += 1
                                if empty_queue_count % 100 == 0 and empty_queue_count > 0:
                                    logging.debug(f"音频队列持续为空 {empty_queue_count} 次")

                        if audio_data and len(audio_data) > 0:
                            played_count += 1
                            # 每播放50个包记录一次日志
                            if played_count % 50 == 0:
                                logging.debug(f"播放音频数据: 包 #{played_count}, {len(audio_data)} 字节")
                            self.stream.write(audio_data)
                        else:
                            # 队列为空时短暂休眠，减少CPU使用
                            time.sleep(0.01)
                    except Exception as e:
                        logging.error(f"播放错误: {e}")
                        # 尝试恢复而不是立即将error_occurred设为True
                        time.sleep(0.05)
                else:
                    logging.warning("音频播放流未激活，尝试重新启动...")
                    try:
                        if self.stream:
                            if not self.stream.is_active():
                                self.stream.start_stream()
                                logging.debug("已重新启动音频播放流")
                    except Exception as e:
                        logging.error(f"重启音频播放流失败: {e}")
                    time.sleep(0.5)
        except Exception as e:
            logging.error(f"播放初始化错误: {e}")
            self.error_occurred = True
        finally:
            self.stop_playback()

    def add_audio(self, audio_data):
        if not audio_data or len(audio_data) == 0:
            return

        # 检查音频数据长度是否符合预期
        expected_length = OPUS_FRAME_SIZE * CHANNELS * 2  # 每个样本2字节 (16位)
        if len(audio_data) != expected_length:
            logging.debug(f"音频数据长度不匹配: 实际={len(audio_data)}, 期望={expected_length}")
            # 如果数据太长或太短，进行调整
            if len(audio_data) < expected_length:
                # 数据太短，用静音(零)填充
                audio_data = audio_data + b'\x00' * (expected_length - len(audio_data))
            else:
                # 数据太长，截断多余部分
                audio_data = audio_data[:expected_length]

        with self.queue_lock:
            # 限制队列大小以减少延迟，但确保有足够的音频数据以保持流畅
            if len(self.audio_queue) > 30:  # 增加队列容量，以处理网络抖动
                # 如果队列过长，丢弃较早的数据以减少延迟
                excess = len(self.audio_queue) - 20  # 保留至少20个包
                self.audio_queue = self.audio_queue[excess:]  # 丢弃过多的包
                logging.debug(f"音频队列过长，丢弃 {excess} 个包")

            # 添加新的音频数据到队列
            self.audio_queue.append(audio_data)
            # 记录每50次队列状态
            if len(self.audio_queue) % 50 == 0:
                logging.debug(f"音频队列当前状态: 长度={len(self.audio_queue)}")

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


class AudioDeviceSelector(QDialog):
    """音频设备选择对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择音频设备")
        self.setFixedSize(400, 200)

        # 设置为模态对话框，阻止其他窗口操作
        self.setWindowModality(Qt.ApplicationModal)

        # 设置窗口置顶
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        # 初始化音频设备列表
        self.input_devices = {}
        self.output_devices = {}
        self.selected_input = None
        self.selected_output = None

        self.init_ui()
        self.load_audio_devices()
        center_window(self)  # 居中显示

    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout()

        # 输入设备选择
        input_label = QLabel("输入设备 (麦克风):")
        self.input_combo = QComboBox()
        self.input_combo.setMinimumWidth(300)

        # 输出设备选择
        output_label = QLabel("输出设备 (扬声器):")
        self.output_combo = QComboBox()
        self.output_combo.setMinimumWidth(300)

        # 确认和取消按钮
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("确认")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)

        layout.addWidget(input_label)
        layout.addWidget(self.input_combo)
        layout.addWidget(output_label)
        layout.addWidget(self.output_combo)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def load_audio_devices(self):
        """加载系统音频设备"""
        try:
            p = pyaudio.PyAudio()

            # 获取默认设备索引
            default_input = p.get_default_input_device_info()["index"]
            default_output = p.get_default_output_device_info()["index"]

            # 遍历所有设备
            for i in range(p.get_device_count()):
                device_info = p.get_device_info_by_index(i)
                device_name = device_info["name"]

                # 添加输入设备
                if device_info["maxInputChannels"] > 0:
                    self.input_devices[i] = device_name
                    self.input_combo.addItem(device_name)
                    # 如果是默认设备，设置为当前选择
                    if i == default_input:
                        self.input_combo.setCurrentText(device_name)
                        self.selected_input = i

                # 添加输出设备
                if device_info["maxOutputChannels"] > 0:
                    self.output_devices[i] = device_name
                    self.output_combo.addItem(device_name)
                    # 如果是默认设备，设置为当前选择
                    if i == default_output:
                        self.output_combo.setCurrentText(device_name)
                        self.selected_output = i

            p.terminate()

            # 连接信号
            self.input_combo.currentTextChanged.connect(self.on_input_changed)
            self.output_combo.currentTextChanged.connect(self.on_output_changed)

            # 如果没有设备，禁用确认按钮
            if not self.input_devices or not self.output_devices:
                self.ok_button.setEnabled(False)
                QMessageBox.warning(self, "设备错误", "未检测到可用的音频设备，请检查系统设置")

        except Exception as e:
            logging.error(f"加载音频设备失败: {e}")
            QMessageBox.critical(self, "设备错误", f"加载音频设备失败: {e}")
            self.ok_button.setEnabled(False)

    def on_input_changed(self, device_name):
        """输入设备变更处理"""
        for idx, name in self.input_devices.items():
            if name == device_name:
                self.selected_input = idx
                break

    def on_output_changed(self, device_name):
        """输出设备变更处理"""
        for idx, name in self.output_devices.items():
            if name == device_name:
                self.selected_output = idx
                break

    def get_selected_devices(self):
        """获取选择的设备索引"""
        return {
            'input': self.selected_input,
            'output': self.selected_output
        }


class CallDialog(QDialog):
    """语音通话对话框"""
    call_ended = pyqtSignal()

    def __init__(self, parent=None, friend_name=None, is_caller=False, udp_thread=None, target_addr=None,
                 username=None):
        super().__init__(parent)
        self.friend_name = friend_name
        self.is_caller = is_caller
        self.udp_thread = udp_thread
        self.target_addr = target_addr
        self.username = username
        self.audio_recorder = None
        self.audio_player = None
        self.call_active = False
        self.error_occurred = False

        # 获取音频设备
        self.audio_devices = self.get_audio_devices()

        self.init_ui()

        if is_caller:
            self.status_label.setText(f"正在等待 {friend_name} 接听...")
        else:
            self.status_label.setText(f"与 {friend_name} 通话中...")
            self.start_call()

    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("语音通话")
        self.setFixedSize(300, 150)

        layout = QVBoxLayout()

        self.status_label = QLabel(f"与 {self.friend_name} 通话中...")
        self.status_label.setAlignment(Qt.AlignCenter)

        self.end_call_btn = QPushButton("结束通话")
        self.end_call_btn.clicked.connect(self.end_call)

        layout.addWidget(self.status_label)
        layout.addWidget(self.end_call_btn)

        self.setLayout(layout)

    def get_audio_devices(self):
        """获取音频设备"""
        dialog = AudioDeviceSelector(self)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.get_selected_devices()
        return {'input': None, 'output': None}

    def start_call(self):
        """开始音频通话"""
        if self.call_active:
            logging.debug("通话已经处于活动状态，忽略再次启动请求")
            return

        logging.debug(f"开始通话准备工作: is_caller={self.is_caller}, target_addr={self.target_addr}")

        # 检查目标地址
        if not self.target_addr:
            logging.error("没有目标地址，无法启动通话")
            QMessageBox.warning(self, "通话失败", "无法获取对方的网络地址，请稍后重试")
            self.call_ended.emit()  # 通知主窗口通话结束
            self.close()
            return

        # 验证目标地址格式
        if not isinstance(self.target_addr, tuple) or len(self.target_addr) != 2:
            logging.error(f"目标地址格式错误: {self.target_addr}")
            QMessageBox.warning(self, "通话失败", "对方网络地址格式错误，请重新尝试")
            self.call_ended.emit()  # 通知主窗口通话结束
            self.close()
            return

        # 特殊IP地址处理
        ip, port = self.target_addr
        if ip in ['0.0.0.0', 'localhost', '']:
            ip = '127.0.0.1'  # 本地测试用127.0.0.1
            self.target_addr = (ip, port)
            logging.debug(f"将目标地址从 {ip} 改为 127.0.0.1")

        # 验证目标地址内容
        if not ip or not port:
            logging.error(f"目标地址内容无效: {self.target_addr}")
            QMessageBox.warning(self, "通话失败", "对方网络地址无效，请确保对方在线")
            self.call_ended.emit()  # 通知主窗口通话结束
            self.close()
            return

        logging.debug(f"准备开始通话: is_caller={self.is_caller}, target_addr={self.target_addr}")

        # 设置通话状态并更新UI
        self.call_active = True
        self.status_label.setText(f"正在连接到 {self.friend_name}...")

        # 尝试发送测试UDP包并等待响应
        udp_test_success = False
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_socket.settimeout(3)  # 增加超时时间到3秒
            test_data = bytes([5]) + b'TEST_CALL'

            # 发送测试数据包到3次，增加成功率
            for attempt in range(3):
                try:
                    test_socket.sendto(test_data, self.target_addr)
                    logging.debug(f"发送UDP测试数据包到 {self.target_addr} (尝试 {attempt + 1}/3)")

                    # 尝试接收响应
                    response, addr = test_socket.recvfrom(1024)
                    if response and len(response) > 0:
                        logging.debug(f"收到UDP测试响应: {response} 来自 {addr}")
                        udp_test_success = True
                        break
                except socket.timeout:
                    logging.warning(f"UDP测试响应超时 (尝试 {attempt + 1}/3)")
                except Exception as e:
                    logging.error(f"UDP测试异常: {e}")
                    break

                # 等待短暂停再尝试
                time.sleep(0.5)

            test_socket.close()
        except Exception as e:
            logging.error(f"UDP连接测试创建失败: {e}")

        # 如果UDP测试失败，显示警告但仍然继续尝试
        if not udp_test_success:
            logging.warning("UDP连接测试失败，但将继续尝试建立通话")
            # 显示警告但不中止通话过程
            QMessageBox.warning(self, "通话警告", "与对方的UDP连接测试失败\n通话可能会有音质问题或连接不稳定的情况")

        try:
            # 验证音频设备
            if 'input' not in self.audio_devices or 'output' not in self.audio_devices:
                raise ValueError("无效的音频设备配置")

            # 获取并记录音频设备详情
            p = pyaudio.PyAudio()
            try:
                input_device_info = p.get_device_info_by_index(self.audio_devices['input'])
                output_device_info = p.get_device_info_by_index(self.audio_devices['output'])
                logging.debug(f"使用输入设备: {input_device_info['name']}")
                logging.debug(f"使用输出设备: {output_device_info['name']}")
            except Exception as e:
                logging.error(f"获取设备信息失败: {e}")
                raise ValueError(f"无法获取音频设备信息: {e}")
            finally:
                p.terminate()

            # 启动音频播放器
            self.audio_player = AudioPlayer(self.audio_devices['output'])
            self.udp_thread.audio_received.connect(self.on_audio_received)
            self.audio_player.start()
            logging.debug("音频播放器启动成功")

            # 启动音频录制器
            self.audio_recorder = AudioRecorder(
                self.udp_thread,
                self.target_addr,
                self.username,
                self.friend_name,
                self.audio_devices['input']
            )
            self.audio_recorder.start()
            logging.debug("音频录制器启动成功")

            # 更新状态
            self.status_label.setText(f"与 {self.friend_name} 通话中...")

            # 添加成功通话提示
            QMessageBox.information(self, "通话已建立", f"您已与 {self.friend_name} 建立通话连接\n语音通话已开始")
        except Exception as e:
            logging.error(f"启动通话失败: {e}", exc_info=True)
            self.error_occurred = True
            QMessageBox.critical(self, "通话错误", f"启动通话失败: {e}")
            self.call_ended.emit()  # 通知主窗口通话结束
            self.close()

    def on_audio_received(self, audio_data):
        """收到音频数据"""
        if self.audio_player and self.call_active and not self.error_occurred:
            try:
                # 减少日志频率，避免日志文件过大
                # logging.debug(f"收到音频数据: {len(audio_data)} 字节")
                if audio_data and len(audio_data) > 0:
                    self.audio_player.add_audio(audio_data)
                else:
                    logging.warning(f"收到空音频数据")
            except Exception as e:
                logging.error(f"处理接收到的音频数据失败: {e}")
                self.error_occurred = True

    def end_call(self):
        """结束通话"""
        if not self.call_active:
            return

        self.call_active = False
        # 停止音频录制和播放
        if self.audio_recorder:
            try:
                self.audio_recorder.stop()
            except Exception as e:
                print(f"停止音频录制器失败: {e}")
            self.audio_recorder = None
        if self.audio_player:
            try:
                self.audio_player.stop()
            except Exception as e:
                print(f"停止音频播放器失败: {e}")
            self.audio_player = None
        if self.udp_thread:
            try:
                self.udp_thread.audio_received.disconnect(self.on_audio_received)
            except Exception as e:
                print(f"断开音频接收信号失败: {e}")
        self.call_ended.emit()
        # 不再主动 self.close()，由主窗口控制

    def closeEvent(self, event):
        self.end_call()
        event.accept()


class IncomingCallDialog(QDialog):
    """来电对话框"""
    call_accepted = pyqtSignal()
    call_rejected = pyqtSignal()

    def __init__(self, parent=None, caller_name=None):
        super().__init__(parent)
        self.caller_name = caller_name
        # 设置窗口为独立窗口，总是在最前，且无法点击其他窗口直到处理通知
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        self.setWindowModality(Qt.ApplicationModal)  # 阻止点击其他窗口

        logging.debug(f"创建来电对话框，来电者: {caller_name}")
        self.init_ui()
        center_window(self)  # 居中显示

        # 播放系统提示音
        QApplication.beep()
        QApplication.beep()  # 播放两次以引起注意

        # 额外创建系统通知，防止窗口被遮挡
        try:
            QMessageBox.information(None, "来电通知", f"收到来自 {caller_name} 的语音通话请求！",
                                    QMessageBox.Ok)
        except:
            pass

    def init_ui(self):
        self.setWindowTitle("【来电提醒】")
        self.setFixedSize(400, 200)

        layout = QVBoxLayout()

        # 使用更显眼的标题
        title_label = QLabel(f"收到来电!")
        title_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: red;")
        title_label.setAlignment(Qt.AlignCenter)

        self.status_label = QLabel(f"{self.caller_name} 正在呼叫你...")
        self.status_label.setStyleSheet("font-size: 14pt;")
        self.status_label.setAlignment(Qt.AlignCenter)

        btn_layout = QHBoxLayout()

        self.accept_btn = QPushButton("接听")
        self.accept_btn.setStyleSheet("background-color: green; color: white; font-size: 12pt; min-height: 40px;")
        self.accept_btn.clicked.connect(self.accept_call)

        self.reject_btn = QPushButton("拒绝")
        self.reject_btn.setStyleSheet("background-color: red; color: white; font-size: 12pt; min-height: 40px;")
        self.reject_btn.clicked.connect(self.reject_call)

        btn_layout.addWidget(self.accept_btn)
        btn_layout.addWidget(self.reject_btn)

        layout.addWidget(title_label)
        layout.addWidget(self.status_label)
        layout.addSpacing(20)
        layout.addLayout(btn_layout)

        self.setLayout(layout)
        logging.debug(f"来电对话框UI初始化完成，来电者: {self.caller_name}")

        # 设置定时提醒
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.reminder_beep)
        self.reminder_timer.start(3000)  # 每3秒提醒一次

    def reminder_beep(self):
        """定期发出提示音"""
        QApplication.beep()

    def accept_call(self):
        logging.debug(f"用户点击接听来自 {self.caller_name} 的通话")
        self.reminder_timer.stop()
        self.call_accepted.emit()
        self.close()

    def reject_call(self):
        logging.debug(f"用户点击拒绝来自 {self.caller_name} 的通话")
        self.reminder_timer.stop()
        self.call_rejected.emit()
        self.close()

    def closeEvent(self, event):
        """窗口关闭时处理"""
        logging.debug(f"来电对话框被关闭")
        self.reminder_timer.stop()
        event.accept()


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
        self.sock.send(f'LOGIN|{username}|{password}'.encode('utf-8'))
        try:
            resp = self.sock.recv(4096).decode('utf-8')
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
        self.sock.send(f'REGISTER|{username}|{password}'.encode('utf-8'))
        resp = self.sock.recv(4096).decode('utf-8')
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
            self.sock.send(f'DELETE_USER|{username}|{password}'.encode('utf-8'))
            resp = self.sock.recv(4096).decode('utf-8')
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

        # 语音通话相关变量
        self.in_call = False
        self.call_target = None
        self.call_dialog = None
        self.incoming_call_dialog = None
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

        # 初始化UDP音频服务
        self.init_udp_audio()

        # 预加载表情
        self.preload_emojis()

        logging.debug(f"初始化UI")
        self.init_ui()

        logging.debug(f"初始刷新好友和群组列表")
        self.initial_refresh()

        # 创建处理来电的专用窗口
        self.call_notification_timer = QTimer(self)
        self.call_notification_timer.timeout.connect(self.check_pending_calls)
        self.call_notification_timer.start(1000)  # 每秒检查一次
        self.pending_calls = []  # 存储待处理的来电

        logging.debug(f"主窗口初始化完成，用户: {username}, UDP端口: {self.udp_local_port}")
        center_window(self)  # 居中显示窗口
        # 在MainWindow.__init__中添加self.current_bg_index = 0
        self.current_bg_index = 0
        self.private_files = []  # 当前私聊文件列表

    def init_udp_audio(self):
        # 分配本地UDP端口并初始化线程
        try:
            # 尝试找到一个可用的端口
            self.udp_local_port = random.randint(UDP_PORT_BASE, UDP_PORT_BASE + 1000)
            max_attempts = 10
            for attempt in range(max_attempts):
                try:
                    # 创建临时套接字测试端口是否可用
                    test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    test_socket.bind(('0.0.0.0', self.udp_local_port))
                    test_socket.close()
                    logging.debug(f"找到可用UDP端口: {self.udp_local_port}")
                    break
                except OSError:
                    self.udp_local_port = random.randint(UDP_PORT_BASE, UDP_PORT_BASE + 1000)
                    if attempt == max_attempts - 1:
                        raise Exception(f"无法找到可用的UDP端口")

            # 使用找到的可用端口初始化UDP线程
            self.udp_thread = UDPAudioThread(self.udp_local_port)
            self.udp_thread.start()
            logging.debug(f"UDP音频线程已启动，端口: {self.udp_local_port}")
        except Exception as e:
            logging.error(f"初始化UDP音频失败: {e}")
            QMessageBox.critical(self, "错误", f"无法初始化音频功能: {e}")

        # 通知服务器我们的UDP端口
        try:
            update_msg = f'UDP_PORT_UPDATE|{self.username}|{self.udp_local_port}'
            logging.debug(f"发送UDP端口更新消息: {update_msg}")
            self.sock.send(update_msg.encode('utf-8'))
        except Exception as e:
            logging.error(f"发送UDP端口更新消息失败: {e}")

        logging.debug(f"UDP音频服务初始化完成，端口: {self.udp_local_port}")

    def preload_emojis(self):
        """预加载所有表情到缓存"""
        try:
            if not os.path.exists(EMOJI_DIR):
                print("表情目录不存在")
                return

            print("开始预加载表情...")
            for fname in os.listdir(EMOJI_DIR):
                if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    path = os.path.join(EMOJI_DIR, fname)
                    if fname.lower().endswith('.gif'):
                        # 加载GIF
                        movie = QMovie(path)
                        movie.setCacheMode(QMovie.CacheAll)
                        self.emoji_cache[fname] = {'type': 'gif', 'movie': movie}
                    else:
                        # 加载静态图片
                        pix = QPixmap(path)
                        scaled_pix = pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self.emoji_cache[fname] = {'type': 'image', 'pixmap': scaled_pix}
            print(f"预加载完成，共 {len(self.emoji_cache)} 个表情")
        except Exception as e:
            print(f"预加载表情出错: {e}")

    def get_emoji_from_cache(self, emoji_id, label):
        """从缓存获取表情并设置到标签"""
        if emoji_id in self.emoji_cache:
            emoji_data = self.emoji_cache[emoji_id]
            if emoji_data['type'] == 'gif':
                movie = emoji_data['movie']
                label.setMovie(movie)
                movie.start()
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
        # 添加语音通话按钮
        self.call_btn = QPushButton('📞')
        self.call_btn.setFixedWidth(40)
        self.call_btn.setToolTip('语音通话')
        self.call_btn.clicked.connect(self.start_voice_call)
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.emoji_btn)
        input_layout.addWidget(self.call_btn)
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
            self.sock.send(f'GET_FRIENDS|{self.username}'.encode('utf-8'))
        except Exception as e:
            print(f"获取好友列表出错: {e}")
            QMessageBox.warning(self, '网络错误', '获取好友列表失败，请检查网络连接')

    def get_groups(self):
        try:
            self.sock.send(f'GET_GROUPS|{self.username}'.encode('utf-8'))
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
        self.get_private_file_list()

    def get_private_history(self):
        """获取与当前好友的私聊历史记录"""
        if not self.current_friend:
            return
        try:
            self.sock.send(f'GET_PRIVATE_HISTORY|{self.username}|{self.current_friend}'.encode('utf-8'))
        except Exception as e:
            print(f"获取私聊历史记录出错: {e}")
            self.append_text_message('[系统]', '获取聊天记录失败，请检查网络连接')

    def add_friend(self):
        friend, ok = QInputDialog.getText(self, '添加好友', '输入好友用户名:')
        if ok and friend:
            self.sock.send(f'ADD_FRIEND|{self.username}|{friend}'.encode('utf-8'))

    def del_friend(self):
        if not self.current_friend:
            QMessageBox.warning(self, '提示', '请先选择要删除的好友')
            return
        self.sock.send(f'DEL_FRIEND|{self.username}|{self.current_friend}'.encode('utf-8'))

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
        self.sock.send(f'MSG|{self.current_friend}|{msg}'.encode('utf-8'))
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
        self.sock.send(f'EMOJI|{self.current_friend}|{emoji_id}'.encode('utf-8'))
        self.append_emoji_message('我', emoji_id)

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
            self.sock.send(f'GET_GROUP_MEMBERS|{self.current_group}'.encode('utf-8'))
            self.sock.send(f'GET_GROUP_HISTORY|{self.current_group}'.encode('utf-8'))
        finally:
            self.selecting_group = False

    def create_group(self):
        group_name, ok = QInputDialog.getText(self, '创建群聊', '输入群聊名称:')
        if ok and group_name:
            self.sock.send(f'CREATE_GROUP|{self.username}|{group_name}'.encode('utf-8'))

    def join_group(self):
        group_id, ok = QInputDialog.getText(self, '加入群聊', '输入群聊ID:')
        if ok and group_id:
            self.sock.send(f'JOIN_GROUP|{self.username}|{group_id}'.encode('utf-8'))

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
            self.sock.send(f'GROUP_MSG_ANON|{self.current_group}|{self.anon_nick}|{msg}'.encode('utf-8'))
            self.append_group_anon_message(self.anon_nick, msg, is_self=True)
        else:
            self.sock.send(f'GROUP_MSG|{self.current_group}|{self.username}|{msg}'.encode('utf-8'))
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
            self.sock.send(f'GROUP_MSG_ANON|{self.current_group}|{self.anon_nick}|[EMOJI]{emoji_id}'.encode('utf-8'))
            self.append_group_anon_emoji(self.anon_nick, emoji_id, is_self=True)
        else:
            self.sock.send(f'GROUP_MSG|{self.current_group}|{self.username}|[EMOJI]{emoji_id}'.encode('utf-8'))
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

            # 语音通话相关消息处理 - 提高优先级，移到前面处理
            if cmd == 'CALL_INCOMING':
                # 收到通话请求
                try:
                    logging.debug("======= CALL_INCOMING详细调试信息 =======")
                    logging.debug(f"收到CALL_INCOMING消息: {data}")
                    caller = parts[1]
                    logging.debug(f"来电者: {caller}")
                    logging.debug(f"当前用户: {self.username}")
                    logging.debug(f"当前通话状态: in_call={self.in_call}, call_target={self.call_target}")
                    logging.debug(f"当前窗口状态: visible={self.isVisible()}, active={self.isActiveWindow()}")

                    # 将来电添加到待处理队列，而不是直接处理
                    if caller not in self.pending_calls:
                        self.pending_calls.append(caller)
                        logging.debug(f"添加来电到待处理队列: {caller}")
                        # 立即触发一次检查
                        QTimer.singleShot(100, self.check_pending_calls)

                    logging.debug("CALL_INCOMING已添加到待处理队列")
                    logging.debug("======= CALL_INCOMING详细调试信息结束 =======")
                except Exception as e:
                    logging.error(f"处理来电请求出错: {e}", exc_info=True)
                    QMessageBox.warning(self, "通话错误", f"处理来电请求失败: {e}")
                # 直接返回以避免后续处理干扰
                return

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
            elif cmd == 'CALL_ACCEPTED':
                # 对方接受通话
                try:
                    if len(parts) < 4:
                        logging.error(f"CALL_ACCEPTED消息格式错误: {data}")
                        QMessageBox.warning(self, "通话错误", "通话连接信息格式错误，请重新尝试")
                        self.in_call = False
                        self.call_target = None
                        return

                    from_user = parts[1]
                    caller_ip = parts[2]
                    caller_port = parts[3]
                    logging.debug(f"收到CALL_ACCEPTED: from={from_user}, ip={caller_ip}, port={caller_port}")
                    logging.debug(f"当前通话状态: in_call={self.in_call}, call_target={self.call_target}")

                    # 验证通话状态
                    if not self.in_call:
                        logging.warning(f"收到来自 {from_user} 的CALL_ACCEPTED，但当前没有活动通话")
                        return

                    if self.call_target != from_user:
                        logging.warning(f"收到来自 {from_user} 的CALL_ACCEPTED，但当前通话目标是 {self.call_target}")
                        return

                    # 处理IP地址和端口
                    # 处理特殊IP地址情况
                    if caller_ip in ['0.0.0.0', 'localhost', '']:
                        # 如果是本地测试，使用127.0.0.1
                        caller_ip = '127.0.0.1'
                        logging.debug(f"将目标地址从 {caller_ip} 改为 127.0.0.1")

                    # 确保端口是有效的整数
                    try:
                        caller_port = int(caller_port)
                        if caller_port <= 0 or caller_port > 65535:
                            raise ValueError(f"无效的端口号: {caller_port}")
                    except ValueError as e:
                        logging.error(f"端口号格式错误: {e}")
                        QMessageBox.warning(self, "通话错误", f"端口号格式错误: {e}")
                        self.in_call = False
                        self.call_target = None
                        return

                    # 设置目标地址
                    target_addr = (caller_ip, caller_port)
                    logging.debug(f"设置通话目标地址: {target_addr}")

                    # 处理通话窗口
                    if self.call_dialog:
                        # 将地址信息更新到通话窗口
                        self.call_dialog.target_addr = target_addr
                        logging.debug(f"已更新通话窗口的目标地址为: {target_addr}")

                        # 启动通话
                        self.call_dialog.start_call()
                        self.call_dialog.status_label.setText(f"与 {from_user} 通话中...")
                        logging.debug("已启动通话并更新状态")

                        # 显示成功通知
                        QMessageBox.information(self, "通话已连接", f"与 {from_user} 的通话已成功建立")
                    else:
                        logging.warning("收到CALL_ACCEPTED但未找到通话窗口，正在创建新窗口")
                        # 如果没有窗口，创建一个新的
                        self.call_dialog = CallDialog(
                            self,
                            from_user,
                            is_caller=True,
                            udp_thread=self.udp_thread,
                            target_addr=target_addr,
                            username=self.username
                        )
                        self.call_dialog.call_ended.connect(self.on_call_ended)
                        self.call_dialog.show()
                        self.call_dialog.start_call()
                except Exception as e:
                    logging.error(f"处理通话接受消息出错: {e}", exc_info=True)
                    QMessageBox.warning(self, "通话错误", f"处理通话接受消息失败: {e}")
                    self.in_call = False
                    self.call_target = None
                return
            elif cmd == 'CALL_REJECTED':
                # 对方拒绝通话
                from_user = parts[1]
                if self.in_call and self.call_target == from_user:
                    QMessageBox.information(self, '通话结束', f'{from_user} 拒绝了通话请求')
                    # 关闭通话对话框
                    if self.call_dialog:
                        self.call_dialog.close()
                    self.in_call = False
                    self.call_target = None
            elif cmd == 'CALL_ENDED':
                # 对方结束通话
                from_user = parts[1]
                if self.in_call and self.call_target == from_user:
                    QMessageBox.information(self, '通话结束', f'{from_user} 结束了通话')
                    # 关闭通话对话框
                    if self.call_dialog:
                        self.call_dialog.close()
                    self.in_call = False
                    self.call_target = None
            elif cmd == 'CALL_RESPONSE':
                # 服务器对通话请求的响应
                status = parts[1]
                target = parts[2]
                if status == 'SENDING':
                    # 新增的状态：服务器正在向目标用户发送通话请求
                    logging.debug(f"服务器确认正在向 {target} 发送通话请求")
                elif status == 'BUSY':
                    QMessageBox.information(self, '通话请求', f'{target} 正在通话中，请稍后再试')
                    if self.call_dialog:
                        self.call_dialog.close()
                    self.in_call = False
                    self.call_target = None
                elif status == 'OFFLINE':
                    QMessageBox.information(self, '通话请求', f'{target} 不在线，无法通话')
                    if self.call_dialog:
                        self.call_dialog.close()
                    self.in_call = False
                    self.call_target = None
                elif status == 'ERROR':
                    # 新增的状态：服务器尝试发送通话请求时出错
                    error_msg = parts[3] if len(parts) > 3 else "未知错误"
                    logging.error(f"通话请求发送失败: {error_msg}")
                    QMessageBox.warning(self, '通话请求失败', f'向 {target} 发送通话请求失败: {error_msg}')
                    if self.call_dialog:
                        self.call_dialog.close()
                    self.in_call = False
                    self.call_target = None
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
            # 结束通话，如果有的话
            if self.in_call and self.call_target:
                try:
                    self.sock.send(f'CALL_END|{self.username}|{self.call_target}'.encode('utf-8'))
                except:
                    pass

            # 清理通话资源
            if self.call_dialog:
                self.call_dialog.close()

            if self.udp_thread:
                self.udp_thread.stop()

            # 尝试发送登出消息，但不等待响应
            try:
                self.sock.send('LOGOUT|'.encode('utf-8'))
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
            self.get_friends()
            self.get_groups()
        except Exception as e:
            print(f"初始化刷新出错: {e}")

    def start_voice_call(self):
        """发起语音通话"""
        logging.debug("尝试发起语音通话")
        if not self.current_friend:
            logging.warning("未选择好友，无法发起通话")
            QMessageBox.warning(self, '提示', '请先选择好友')
            return

        if self.in_call:
            logging.warning("已在通话中，无法发起新通话")
            QMessageBox.warning(self, '提示', '你已经在通话中')
            return

        # 检查好友是否在线
        if self.current_friend not in self.friend_status or self.friend_status[self.current_friend] != 'online':
            logging.warning(f"好友 {self.current_friend} 不在线")
            QMessageBox.warning(self, '提示', f'{self.current_friend} 当前不在线')
            return

        # 发送通话请求到服务器
        try:
            logging.debug(f"发起语音通话请求：{self.username} -> {self.current_friend}")
            call_request = f'CALL_REQUEST|{self.username}|{self.current_friend}|{self.udp_local_port}'
            logging.debug(f"准备发送通话请求: {call_request}")
            self.sock.send(call_request.encode('utf-8'))
            logging.debug(f"已发送CALL_REQUEST消息，本地UDP端口: {self.udp_local_port}")
            self.in_call = True
            self.call_target = self.current_friend

            # 创建通话对话框
            self.call_dialog = CallDialog(
                self,
                self.current_friend,
                is_caller=True,
                udp_thread=self.udp_thread,
                username=self.username
            )
            self.call_dialog.call_ended.connect(self.on_call_ended)
            self.call_dialog.show()
            logging.debug(f"已创建通话对话框(主叫方)")
        except Exception as e:
            self.in_call = False
            self.call_target = None
            logging.error(f"发起通话请求失败: {e}", exc_info=True)
            QMessageBox.warning(self, '错误', f'发起通话失败: {e}')

    def on_call_ended(self):
        """通话结束处理"""
        if self.call_target:
            try:
                # 发送通话结束消息
                self.sock.send(f'CALL_END|{self.username}|{self.call_target}'.encode('utf-8'))
            except Exception as e:
                print(f"发送通话结束消息失败: {e}")

        self.in_call = False
        self.call_target = None
        self.call_dialog = None

    def check_pending_calls(self):
        """定期检查待处理的来电并显示通知"""
        if not self.pending_calls:
            return

        # 处理队列中的第一个来电
        caller = self.pending_calls[0]
        logging.debug(f"从待处理队列中处理来电: {caller}")

        # 如果已经在通话中，自动拒绝
        if self.in_call:
            logging.debug(f"已在通话中，自动拒绝来电: {caller}")
            try:
                self.sock.send(f'CALL_REJECT|{self.username}|{caller}'.encode('utf-8'))
            except Exception as e:
                logging.error(f"发送拒绝通话消息失败: {e}")
            self.pending_calls.remove(caller)
            return

        # 如果已经有通知窗口在显示，先关闭它
        if hasattr(self, 'notification_window') and self.notification_window and self.notification_window.isVisible():
            try:
                self.notification_window.close()
            except:
                pass
            self.notification_window = None

        # 创建新的通知窗口
        try:
            # 创建独立的通知窗口
            self.notification_window = CallNotificationWindow(caller)
            self.notification_window.accept_signal.connect(lambda c: self.accept_incoming_call(c))
            self.notification_window.reject_signal.connect(lambda c: self.reject_incoming_call(c))

            # 确保窗口显示在最前面
            self.notification_window.setWindowState(self.notification_window.windowState() | Qt.WindowActive)
            self.notification_window.show()
            self.notification_window.raise_()
            self.notification_window.activateWindow()

            # 播放系统提示音
            QApplication.beep()
            QApplication.beep()  # 播放两次以引起注意

            # 从队列中移除
            self.pending_calls.remove(caller)
            logging.debug(f"已显示通知窗口并从队列中移除: {caller}")
        except Exception as e:
            logging.error(f"创建通知窗口失败: {e}", exc_info=True)
            # 出错时也从队列中移除，避免重复处理
            if caller in self.pending_calls:
                self.pending_calls.remove(caller)

    def accept_incoming_call(self, caller):
        """接受来电"""
        logging.debug(f"接受来电：{caller}")
        try:
            self.in_call = True
            self.call_target = caller

            # 发送接受通话消息
            accept_msg = f'CALL_ACCEPT|{self.username}|{caller}|{self.udp_local_port}'.encode('utf-8')
            logging.debug(f"准备发送CALL_ACCEPT: {accept_msg}")
            self.sock.send(accept_msg)
            logging.debug(f"已发送CALL_ACCEPT消息，本地UDP端口: {self.udp_local_port}")

            # 创建通话对话框 - 这一步是关键
            # 此时我们还不知道对方的UDP地址，但可以先创建对话框
            # 当收到CALL_ACCEPTED消息时会通过create_call_dialog_as_receiver更新
            self.call_dialog = CallDialog(
                self,
                caller,
                is_caller=False,  # 作为接收方
                udp_thread=self.udp_thread,
                username=self.username
            )
            self.call_dialog.call_ended.connect(self.on_call_ended)
            self.call_dialog.show()
            logging.debug(f"已创建通话对话框(被叫方)")

        except Exception as e:
            self.in_call = False
            self.call_target = None
            logging.error(f"接受通话失败: {e}")
            QMessageBox.warning(self, '错误', f'接受通话失败: {e}')

    def reject_incoming_call(self, caller):
        """拒绝来电"""
        try:
            self.sock.send(f'CALL_REJECT|{self.username}|{caller}'.encode('utf-8'))
            logging.debug(f"已发送拒绝通话消息: CALL_REJECT|{self.username}|{caller}")
        except Exception as e:
            logging.error(f"拒绝通话失败: {e}")

        self.incoming_call_dialog = None

    def create_call_dialog_as_receiver(self, caller, caller_ip, caller_port):
        """作为接收方创建通话对话框"""
        target_addr = (caller_ip, int(caller_port))
        logging.debug(f"创建/更新接收方通话对话框，目标地址: {target_addr}")
        if self.call_dialog:
            self.call_dialog.target_addr = target_addr
            self.call_dialog.start_call()
            logging.debug(f"已更新接收方通话对话框的目标地址并开始通话")
        else:
            self.call_dialog = CallDialog(
                self,
                caller,
                is_caller=False,
                udp_thread=self.udp_thread,
                target_addr=target_addr,
                username=self.username
            )
            self.call_dialog.call_ended.connect(self.on_call_ended)
            self.call_dialog.show()
            logging.debug(f"已创建新的接收方通话对话框")

    def handle_incoming_call(self, caller):
        """处理来电 - 保留此方法以兼容旧代码"""
        logging.debug(f"handle_incoming_call被调用: {caller}")
        if caller not in self.pending_calls:
            self.pending_calls.append(caller)
            QTimer.singleShot(100, self.check_pending_calls)

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
            self.sock.send(
                f'FILE_UPLOAD_START|{self.username}|{self.current_friend}|{os.path.basename(file_path)}|{os.path.getsize(file_path)}|1'.encode(
                    'utf-8'))

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
            self.sock.send(f'FILE_DOWNLOAD_START|{self.username}|{self.current_friend}|{fname}'.encode('utf-8'))

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
            self.sock.send(f'FILE_LIST|{self.username}|{self.current_friend}'.encode('utf-8'))
        except Exception as e:
            QMessageBox.warning(self, '网络错误', f'获取文件列表失败: {e}')

    def update_private_file_list(self, file_list):
        self.private_files = file_list
        self.file_list.clear()
        for fname in file_list:
            self.file_list.addItem(fname)


class CallNotificationWindow(QWidget):
    """独立的通话通知窗口，不会受到主窗口状态的影响"""

    accept_signal = pyqtSignal(str)  # 接受通话信号
    reject_signal = pyqtSignal(str)  # 拒绝通话信号

    def __init__(self, caller):
        super().__init__(None)  # 没有父窗口，完全独立窗口
        self.caller = caller
        # 修改窗口标志，确保窗口始终可见且在最前面
        self.setWindowFlags(
            Qt.Window |  # 独立窗口
            Qt.WindowStaysOnTopHint |  # 保持在最前面
            Qt.FramelessWindowHint  # 无边框
        )

        # 设置窗口样式
        self.setStyleSheet("""
            QWidget {
                background-color: #302F3D;
                color: white;
                border: 2px solid #FF5555;
                border-radius: 10px;
            }
            QLabel {
                color: white;
            }
            QPushButton {
                background-color: #444;
                color: white;
                border-radius: 5px;
                padding: 8px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #555;
            }
            #acceptButton {
                background-color: #28a745;
            }
            #acceptButton:hover {
                background-color: #218838;
            }
            #rejectButton {
                background-color: #dc3545;
            }
            #rejectButton:hover {
                background-color: #c82333;
            }
        """)

        self.init_ui()
        self.move_to_corner()

        # 播放提示音
        QApplication.beep()
        QApplication.beep()  # 播放两次以引起注意

        # 设置定时器自动关闭
        self.auto_close_timer = QTimer(self)
        self.auto_close_timer.timeout.connect(self.on_auto_close)
        self.auto_close_timer.start(30000)  # 30秒后自动关闭

        # 设置定时提醒
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.reminder_beep)
        self.reminder_timer.start(3000)  # 每3秒提醒一次

        # 记录开始时间
        self.start_time = time.time()

        # 更新剩余时间的定时器
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_time_left)
        self.update_timer.start(1000)  # 每秒更新一次

        # 确保窗口显示在最前面
        self.show()
        self.raise_()
        self.activateWindow()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)  # 设置边距

        # 头部标签
        title_label = QLabel(f"📞 来电通知")
        title_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #FF5555;")
        title_label.setAlignment(Qt.AlignCenter)

        # 通话信息
        caller_label = QLabel(f"<b>{self.caller}</b> 正在呼叫你")
        caller_label.setStyleSheet("font-size: 14pt;")
        caller_label.setAlignment(Qt.AlignCenter)

        # 剩余时间显示
        self.time_label = QLabel("30秒后自动拒绝")
        self.time_label.setAlignment(Qt.AlignCenter)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)  # 设置按钮间距

        self.accept_btn = QPushButton("接听")
        self.accept_btn.setObjectName("acceptButton")
        self.accept_btn.setMinimumHeight(40)
        self.accept_btn.setCursor(Qt.PointingHandCursor)  # 设置鼠标指针
        self.accept_btn.clicked.connect(self.on_accept)

        self.reject_btn = QPushButton("拒绝")
        self.reject_btn.setObjectName("rejectButton")
        self.reject_btn.setMinimumHeight(40)
        self.reject_btn.setCursor(Qt.PointingHandCursor)  # 设置鼠标指针
        self.reject_btn.clicked.connect(self.on_reject)

        btn_layout.addWidget(self.accept_btn)
        btn_layout.addWidget(self.reject_btn)

        # 组装布局
        layout.addWidget(title_label)
        layout.addWidget(caller_label)
        layout.addWidget(self.time_label)
        layout.addLayout(btn_layout)

        self.setLayout(layout)
        self.setFixedSize(300, 200)

    def move_to_corner(self):
        """将窗口移动到屏幕右下角"""
        screen = QDesktopWidget().screenGeometry()
        widget_size = self.size()
        self.move(screen.width() - widget_size.width() - 20,
                  screen.height() - widget_size.height() - 60)

    def reminder_beep(self):
        """定期发出提示音"""
        QApplication.beep()

    def update_time_left(self):
        """更新剩余时间显示"""
        elapsed = time.time() - self.start_time
        remaining = max(0, 30 - int(elapsed))
        self.time_label.setText(f"{remaining}秒后自动拒绝")

    def on_accept(self):
        """接受通话"""
        self.auto_close_timer.stop()
        self.reminder_timer.stop()
        self.update_timer.stop()
        self.accept_signal.emit(self.caller)
        self.close()

    def on_reject(self):
        """拒绝通话"""
        self.auto_close_timer.stop()
        self.reminder_timer.stop()
        self.update_timer.stop()
        self.reject_signal.emit(self.caller)
        self.close()

    def on_auto_close(self):
        """自动关闭并拒绝通话"""
        self.reject_signal.emit(self.caller)
        self.close()

    def closeEvent(self, event):
        """关闭窗口时确保定时器停止"""
        self.auto_close_timer.stop()
        self.reminder_timer.stop()
        self.update_timer.stop()
        event.accept()

    def mousePressEvent(self, event):
        """允许通过点击窗口任意位置来拖动窗口"""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """处理窗口拖动"""
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()


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