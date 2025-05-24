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
import random
import shutil
import tkinter.filedialog
import tkinter.messagebox
import json
import threading
import hashlib

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
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 12345
UDP_PORT_BASE = 40000

EMOJI_DIR = os.path.join(os.path.dirname(__file__), 'resources')
BG_DIR = os.path.join(os.path.dirname(__file__), 'backgrounds')
os.makedirs(BG_DIR, exist_ok=True)

FILES_DIR = os.path.join(os.path.dirname(__file__), 'files')
os.makedirs(FILES_DIR, exist_ok=True)

# 音频配置
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000


def center_window(window):
    """将窗口定位到屏幕中央"""
    screen = QDesktopWidget().screenGeometry()
    size = window.geometry()
    window.move((screen.width() - size.width()) // 2,
                (screen.height() - size.height()) // 2)


def check_network_config():
    """检查网络配置"""
    try:
        socket.gethostbyname(SERVER_HOST)
        logging.debug(f"服务器地址 {SERVER_HOST} 解析成功")

        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(5)
        test_sock.connect((SERVER_HOST, SERVER_PORT))
        test_sock.close()
        logging.debug(f"成功连接到服务器 {SERVER_HOST}:{SERVER_PORT}")
        return True
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
        self.buffer = b''
        logging.debug("客户端线程初始化")

    def run(self):
        logging.debug("客户端线程开始运行")
        self.sock.settimeout(1.0)

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
        self.udp_socket.settimeout(0.5)
        self.running = True
        self.error_occurred = False
        logging.debug(f"UDP音频线程绑定到端口: {self.local_port}")

    def run(self):
        while self.running and not self.error_occurred:
            try:
                data, addr = self.udp_socket.recvfrom(65536)
                if data and len(data) > 1:
                    try:
                        header_len = data[0]
                        if len(data) > header_len + 1:
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

            header = f"{sender}|{receiver}"
            header_bytes = header.encode('utf-8')
            header_len = len(header_bytes)

            packet = bytearray([header_len]) + header_bytes + audio_data
            self.udp_socket.sendto(packet, target_addr)
            logging.debug(f"发送UDP音频数据: {len(audio_data)} 字节，到: {target_addr}")
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


class AudioDeviceSelector(QDialog):
    """音频设备选择对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择音频设备")
        self.setFixedSize(400, 300)
        self.audio = pyaudio.PyAudio()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        input_layout = QVBoxLayout()
        input_layout.addWidget(QLabel("选择输入设备:"))
        self.input_combo = QComboBox()
        self.populate_input_devices()
        input_layout.addWidget(self.input_combo)

        output_layout = QVBoxLayout()
        output_layout.addWidget(QLabel("选择输出设备:"))
        self.output_combo = QComboBox()
        self.populate_output_devices()
        output_layout.addWidget(self.output_combo)

        self.ok_button = QPushButton("确定")
        self.ok_button.clicked.connect(self.accept)

        layout.addLayout(input_layout)
        layout.addLayout(output_layout)
        layout.addWidget(self.ok_button)
        self.setLayout(layout)

    def populate_input_devices(self):
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if device_info['maxInputChannels'] > 0:
                self.input_combo.addItem(device_info['name'], i)

    def populate_output_devices(self):
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if device_info['maxOutputChannels'] > 0:
                self.output_combo.addItem(device_info['name'], i)

    def get_selected_devices(self):
        return {
            'input': self.input_combo.currentData(),
            'output': self.output_combo.currentData()
        }

    def closeEvent(self, event):
        self.audio.terminate()
        event.accept()


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
            self.audio = pyaudio.PyAudio()
            device_info = self.audio.get_device_info_by_index(self.input_device_index)
            logging.debug(f"使用输入设备: {device_info['name']}")

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

            self.stream.start_stream()
            logging.debug("开始录音...")

            while self.running and not self.error_occurred:
                if self.stream and self.stream.is_active():
                    try:
                        audio_data = self.stream.read(CHUNK, exception_on_overflow=False)
                        if audio_data and len(audio_data) > 0:
                            logging.debug(f"录制到音频数据: {len(audio_data)} 字节")
                            self.udp_thread.send_audio(audio_data, self.target_addr, self.sender, self.receiver)
                    except Exception as e:
                        logging.error(f"录音错误: {e}")
                        self.error_occurred = True
                        time.sleep(0.1)
                else:
                    logging.warning("音频流未激活")
                    time.sleep(0.1)
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
            self.audio = pyaudio.PyAudio()
            device_info = self.audio.get_device_info_by_index(self.output_device_index)
            logging.debug(f"使用输出设备: {device_info['name']}")

            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                frames_per_buffer=CHUNK,
                output_device_index=self.output_device_index,
                stream_callback=None,
                start=True
            )

            logging.debug("开始音频播放...")

            while self.running and not self.error_occurred:
                if self.audio_queue and self.stream and self.stream.is_active():
                    try:
                        with self.queue_lock:
                            if self.audio_queue:
                                audio_data = self.audio_queue.pop(0)
                                if audio_data and len(audio_data) > 0:
                                    logging.debug(f"播放音频数据: {len(audio_data)} 字节")
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
            if len(self.audio_queue) > 10:
                self.audio_queue = self.audio_queue[5:]
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
        self.audio_devices = None

        self.init_ui()

        if is_caller:
            self.status_label.setText(f"正在等待 {friend_name} 接听...")
        else:
            self.status_label.setText(f"与 {friend_name} 通话中...")
            # 延迟获取音频设备，避免阻塞UI
            QTimer.singleShot(500, self.delayed_start_call)

    def delayed_start_call(self):
        """延迟启动通话，避免阻塞UI"""
        try:
            # 获取音频设备
            self.audio_devices = self.get_audio_devices()
            if self.audio_devices and self.audio_devices['input'] is not None and self.audio_devices[
                'output'] is not None:
                self.start_call()
            else:
                QMessageBox.warning(self, '错误', '音频设备获取失败，无法开始通话')
                self.end_call()
        except Exception as e:
            logging.error(f"延迟启动通话失败: {e}")
            QMessageBox.warning(self, '错误', f'启动通话失败: {e}')
            self.end_call()

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
            return

        logging.debug(f"开始通话: is_caller={self.is_caller}, target_addr={self.target_addr}")

        # 检查是否有目标地址
        if not self.target_addr:
            logging.warning("没有目标地址，等待对方接受通话")
            if self.is_caller:
                self.status_label.setText(f"正在等待 {self.friend_name} 接听...")
                return
            else:
                logging.error("接收方没有目标地址，这是一个错误")
                self.error_occurred = True
                self.end_call()
                return

        self.call_active = True
        self.status_label.setText(f"与 {self.friend_name} 通话中...")

        try:
            # 启动音频播放器
            if self.audio_devices and self.audio_devices['output'] is not None:
                self.audio_player = AudioPlayer(self.audio_devices['output'])
                self.udp_thread.audio_received.connect(self.on_audio_received)
                self.audio_player.start()
                logging.debug("音频播放器已启动")

            # 启动音频录制器
            if self.audio_devices and self.audio_devices['input'] is not None:
                self.audio_recorder = AudioRecorder(
                    self.udp_thread,
                    self.target_addr,
                    self.username,
                    self.friend_name,
                    self.audio_devices['input']
                )
                self.audio_recorder.start()
                logging.debug("音频录制器已启动")

        except Exception as e:
            logging.error(f"启动通话失败: {e}")
            self.error_occurred = True
            self.end_call()

    def update_target_addr(self, target_addr):
        """更新目标地址，用于主叫方接收到对方地址后启动通话"""
        self.target_addr = target_addr
        logging.debug(f"更新目标地址: {target_addr}")
        if self.is_caller and not self.call_active:
            # 如果是主叫方且还没开始通话，现在可以开始了
            if not self.audio_devices:
                self.audio_devices = self.get_audio_devices()
            if self.audio_devices and self.audio_devices['input'] is not None and self.audio_devices[
                'output'] is not None:
                self.start_call()

    def on_audio_received(self, audio_data):
        """收到音频数据"""
        if self.audio_player and self.call_active and not self.error_occurred:
            try:
                logging.debug(f"收到音频数据: {len(audio_data)} 字节")
                self.audio_player.add_audio(audio_data)
            except Exception as e:
                logging.error(f"处理接收到的音频数据失败: {e}")
                self.error_occurred = True

    def end_call(self):
        """结束通话"""
        logging.debug("结束通话")
        self.call_active = False

        # 停止音频录制和播放
        if self.audio_recorder:
            try:
                self.audio_recorder.stop()
            except Exception as e:
                logging.error(f"停止音频录制器失败: {e}")
            self.audio_recorder = None

        if self.audio_player:
            try:
                self.audio_player.stop()
            except Exception as e:
                logging.error(f"停止音频播放器失败: {e}")
            self.audio_player = None

        if self.udp_thread:
            try:
                self.udp_thread.audio_received.disconnect(self.on_audio_received)
            except Exception as e:
                logging.error(f"断开音频接收信号失败: {e}")

        self.call_ended.emit()
        self.close()

    def closeEvent(self, event):
        """窗口关闭时结束通话"""
        if self.call_active:
            self.end_call()
        event.accept()


def excepthook(type, value, traceback):
    QMessageBox.critical(None, '未捕获异常', str(value))
    sys.__excepthook__(type, value, traceback)


sys.excepthook = excepthook


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('登录/注册')

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
            self.show()

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
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.setWindowFlags(self.windowFlags() | Qt.Tool)

        self.emoji_layout = QHBoxLayout()
        self.layout.addLayout(self.emoji_layout)

        self.upload_btn = QPushButton('上传表情')
        self.upload_btn.clicked.connect(self.upload_emoji)
        self.layout.addWidget(self.upload_btn)
        self.load_emojis()

    def load_emojis(self):
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
        self.unread_groups = set()
        self.anon_mode = False
        self.anon_nick = None
        self.selecting_group = False

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
        self.call_notification_timer.start(1000)
        self.pending_calls = []

        logging.debug(f"主窗口初始化完成，用户: {username}, UDP端口: {self.udp_local_port}")
        center_window(self)
        self.current_bg_index = 0
        self.private_files = []

    def init_udp_audio(self):
        """初始化UDP音频通信"""
        logging.debug("开始初始化UDP音频服务")

        self.udp_local_port = random.randint(40000, 65000)
        logging.debug(f"分配随机UDP端口: {self.udp_local_port}")

        port_attempts = 0
        while port_attempts < 20:
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
                self.udp_local_port = random.randint(40000, 65000)

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
                        movie = QMovie(path)
                        movie.setCacheMode(QMovie.CacheAll)
                        self.emoji_cache[fname] = {'type': 'gif', 'movie': movie}
                    else:
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

        # 背景切换按钮和分辨率调整按钮
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

        if not self.get_emoji_from_cache(emoji_id, img_label):
            path = os.path.join(EMOJI_DIR, emoji_id)
            if not os.path.exists(path):
                print(f"表情文件不存在: {path}")
                img_label.setText(f"[表情: {emoji_id}]")
            elif emoji_id.lower().endswith('.gif'):
                movie = QMovie(path)
                img_label.setMovie(movie)
                movie.setCacheMode(QMovie.CacheAll)
                movie.start()
                QApplication.processEvents()
            else:
                pix = QPixmap(path)
                if pix.isNull():
                    print(f"表情加载失败，尝试重新加载: {emoji_id}")
                    pix = QPixmap(path)
                img_label.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                QApplication.processEvents()

        layout.addWidget(name_label)
        layout.addWidget(img_label)
        widget.setLayout(layout)
        item = QListWidgetItem()
        self.chat_display.addItem(item)
        self.chat_display.setItemWidget(item, widget)
        item.setSizeHint(widget.sizeHint())
        self.chat_display.scrollToBottom()
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
            group_info = str(group_info)
            if self.current_group and str(self.current_group) == group_info:
                self.selecting_group = False
                return

            self.current_group = group_info
            if group_info in self.unread_groups:
                self.unread_groups.remove(group_info)
                self.update_group_list()
            self.tab_widget.setCurrentWidget(self.group_tab)
            self.group_chat_display.clear()
            self.anon_nick = None
            self.group_members_list.clear()
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

        if not self.get_emoji_from_cache(emoji_id, img_label):
            path = os.path.join(EMOJI_DIR, emoji_id)
            if not os.path.exists(path):
                print(f"表情文件不存在: {path}")
                img_label.setText(f"[表情: {emoji_id}]")
            elif emoji_id.lower().endswith('.gif'):
                movie = QMovie(path)
                img_label.setMovie(movie)
                movie.setCacheMode(QMovie.CacheAll)
                movie.start()
                QApplication.processEvents()
            else:
                pix = QPixmap(path)
                if pix.isNull():
                    print(f"表情加载失败，尝试重新加载: {emoji_id}")
                    pix = QPixmap(path)
                img_label.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
        self.group_chat_display.repaint()

    def append_group_anon_emoji(self, anon_nick, emoji_id, is_self=False):
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel(f'<b>{anon_nick}(匿名):</b>')
        img_label = QLabel()

        if not self.get_emoji_from_cache(emoji_id, img_label):
            path = os.path.join(EMOJI_DIR, emoji_id)
            if not os.path.exists(path):
                print(f"表情文件不存在: {path}")
                img_label.setText(f"[表情: {emoji_id}]")
            elif emoji_id.lower().endswith('.gif'):
                movie = QMovie(path)
                img_label.setMovie(movie)
                movie.setCacheMode(QMovie.CacheAll)
                movie.start()
                QApplication.processEvents()
            else:
                pix = QPixmap(path)
                if pix.isNull():
                    print(f"表情加载失败，尝试重新加载: {emoji_id}")
                    pix = QPixmap(path)
                img_label.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
        self.group_chat_display.repaint()

    def on_message(self, data):
        """处理收到的消息 - 简化版本，专注于通话功能"""
        try:
            logging.debug(f"处理收到的消息: {data}")
            parts = data.split('|')
            cmd = parts[0]

            if cmd == 'FORCE_LOGOUT':
                reason = parts[1] if len(parts) > 1 else "您的账号在其他地方登录"
                logging.warning(f"账号被强制下线: {reason}")
                QMessageBox.warning(self, "强制下线", reason)
                self.close()
                return

            elif cmd == 'CALL_INCOMING':
                try:
                    logging.debug(f"收到CALL_INCOMING消息: {data}")
                    caller = parts[1]
                    logging.debug(f"来电者: {caller}")

                    if caller not in self.pending_calls:
                        self.pending_calls.append(caller)
                        logging.debug(f"添加来电到待处理队列: {caller}")
                        QTimer.singleShot(100, self.check_pending_calls)
                except Exception as e:
                    logging.error(f"处理来电请求出错: {e}", exc_info=True)
                return

            elif cmd == 'CALL_ACCEPTED':
                try:
                    if len(parts) < 4:
                        logging.error(f"CALL_ACCEPTED消息格式错误: {data}")
                        return

                    from_user = parts[1]
                    caller_ip = parts[2]
                    caller_port = parts[3]

                    logging.debug(f"收到CALL_ACCEPTED: from={from_user}, ip={caller_ip}, port={caller_port}")

                    if self.in_call and self.call_target == from_user:
                        target_addr = (caller_ip, int(caller_port))
                        logging.debug(f"收到对方UDP地址: {target_addr}")

                        if self.call_dialog:
                            logging.debug("更新主叫方通话对话框并开始通话")
                            self.call_dialog.update_target_addr(target_addr)
                            self.call_dialog.status_label.setText(f"与 {from_user} 通话中...")
                        else:
                            logging.debug("为被叫方创建通话对话框")
                            self.create_call_dialog_as_receiver(from_user, caller_ip, caller_port)
                except Exception as e:
                    logging.error(f"处理通话接受消息出错: {e}", exc_info=True)
                return

            elif cmd == 'CALL_REJECTED':
                from_user = parts[1]
                if self.in_call and self.call_target == from_user:
                    QMessageBox.information(self, '通话结束', f'{from_user} 拒绝了通话请求')
                    if self.call_dialog:
                        self.call_dialog.close()
                    self.in_call = False
                    self.call_target = None

            elif cmd == 'CALL_ENDED':
                from_user = parts[1]
                if self.in_call and self.call_target == from_user:
                    QMessageBox.information(self, '通话结束', f'{from_user} 结束了通话')
                    if self.call_dialog:
                        self.call_dialog.close()
                    self.in_call = False
                    self.call_target = None

            elif cmd == 'CALL_RESPONSE':
                status = parts[1]
                target = parts[2]
                if status == 'SENDING':
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
                    error_msg = parts[3] if len(parts) > 3 else "未知错误"
                    logging.error(f"通话请求发送失败: {error_msg}")
                    QMessageBox.warning(self, '通话请求失败', f'向 {target} 发送通话请求失败: {error_msg}')
                    if self.call_dialog:
                        self.call_dialog.close()
                    self.in_call = False
                    self.call_target = None

            # 其他消息处理...
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

            elif cmd == 'MSG':
                from_user, msg = parts[1], '|'.join(parts[2:])
                if self.tab_widget.currentWidget() == self.private_tab and from_user == self.current_friend:
                    self.append_text_message(from_user, msg)

            elif cmd == 'EMOJI':
                from_user, emoji_id = parts[1], parts[2]
                if self.tab_widget.currentWidget() == self.private_tab and from_user == self.current_friend:
                    self.append_emoji_message(from_user, emoji_id)

            # 继续处理其他消息类型...

        except Exception as e:
            logging.error(f"处理消息时出错: {e}, 消息内容: {data}", exc_info=True)

    def update_friend_status(self, username, online):
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
        self.close()
        self.login_window = LoginWindow()
        self.login_window.show()

    def closeEvent(self, event):
        try:
            if self.in_call and self.call_target:
                try:
                    self.sock.send(f'CALL_END|{self.username}|{self.call_target}'.encode('utf-8'))
                except:
                    pass

            if self.call_dialog:
                self.call_dialog.close()

            if self.udp_thread:
                self.udp_thread.stop()

            try:
                self.sock.send('LOGOUT|'.encode('utf-8'))
            except:
                pass

            self.client_thread.stop()

            try:
                self.sock.close()
            except:
                pass

            event.accept()

            if event.spontaneous():
                QApplication.quit()

        except Exception as e:
            print(f"关闭窗口时出错: {e}")
            event.accept()
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

        if self.current_friend not in self.friend_status or self.friend_status[self.current_friend] != 'online':
            logging.warning(f"好友 {self.current_friend} 不在线")
            QMessageBox.warning(self, '提示', f'{self.current_friend} 当前不在线')
            return

        try:
            logging.debug(f"发起语音通话请求：{self.username} -> {self.current_friend}")
            call_request = f'CALL_REQUEST|{self.username}|{self.current_friend}|{self.udp_local_port}'
            logging.debug(f"准备发送通话请求: {call_request}")
            self.sock.send(call_request.encode('utf-8'))
            logging.debug(f"已发送CALL_REQUEST消息，本地UDP端口: {self.udp_local_port}")
            self.in_call = True
            self.call_target = self.current_friend

            # 创建通话对话框 - 主叫方先不设置target_addr
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

        caller = self.pending_calls[0]
        logging.debug(f"从待处理队列中处理来电: {caller}")

        if self.in_call:
            logging.debug(f"已在通话中，自动拒绝来电: {caller}")
            try:
                self.sock.send(f'CALL_REJECT|{self.username}|{caller}'.encode('utf-8'))
            except Exception as e:
                logging.error(f"发送拒绝通话消息失败: {e}")
            self.pending_calls.remove(caller)
            return

        if hasattr(self, 'notification_window') and self.notification_window and self.notification_window.isVisible():
            try:
                self.notification_window.close()
            except:
                pass
            self.notification_window = None

        try:
            self.notification_window = CallNotificationWindow(caller)
            self.notification_window.accept_signal.connect(lambda c: self.accept_incoming_call(c))
            self.notification_window.reject_signal.connect(lambda c: self.reject_incoming_call(c))

            self.notification_window.setWindowState(self.notification_window.windowState() | Qt.WindowActive)
            self.notification_window.show()
            self.notification_window.raise_()
            self.notification_window.activateWindow()

            QApplication.beep()
            QApplication.beep()

            self.pending_calls.remove(caller)
            logging.debug(f"已显示通知窗口并从队列中移除: {caller}")
        except Exception as e:
            logging.error(f"创建通知窗口失败: {e}", exc_info=True)
            if caller in self.pending_calls:
                self.pending_calls.remove(caller)

    def accept_incoming_call(self, caller):
        """接受来电"""
        logging.debug(f"接受来电：{caller}")
        try:
            self.in_call = True
            self.call_target = caller

            accept_msg = f'CALL_ACCEPT|{self.username}|{caller}|{self.udp_local_port}'.encode('utf-8')
            logging.debug(f"准备发送CALL_ACCEPT: {accept_msg}")
            self.sock.send(accept_msg)
            logging.debug(f"已发送CALL_ACCEPT消息，本地UDP端口: {self.udp_local_port}")

            # 创建通话对话框 - 被叫方，等待收到CALL_ACCEPTED消息后设置target_addr
            self.call_dialog = CallDialog(
                self,
                caller,
                is_caller=False,
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
        if self.call_dialog or not self.in_call:
            return

        target_addr = (caller_ip, int(caller_port))
        logging.debug(f"创建接收方通话对话框，目标地址: {target_addr}")

        if self.call_dialog:
            self.call_dialog.update_target_addr(target_addr)
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

    # 简化的文件传输功能 - 省略详细实现以专注于通话功能
    def upload_private_file(self):
        QMessageBox.information(self, '提示', '文件传输功能已简化，请在完整版本中使用')

    def download_private_file(self, item):
        QMessageBox.information(self, '提示', '文件传输功能已简化，请在完整版本中使用')

    def get_private_file_list(self):
        pass

    def update_private_file_list(self, file_list):
        pass


class CallNotificationWindow(QWidget):
    """独立的通话通知窗口"""

    accept_signal = pyqtSignal(str)
    reject_signal = pyqtSignal(str)

    def __init__(self, caller):
        super().__init__(None)
        self.caller = caller
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint
        )

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

        QApplication.beep()
        QApplication.beep()

        self.auto_close_timer = QTimer(self)
        self.auto_close_timer.timeout.connect(self.on_auto_close)
        self.auto_close_timer.start(30000)

        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.reminder_beep)
        self.reminder_timer.start(3000)

        self.start_time = time.time()

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_time_left)
        self.update_timer.start(1000)

        self.show()
        self.raise_()
        self.activateWindow()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        title_label = QLabel(f"📞 来电通知")
        title_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #FF5555;")
        title_label.setAlignment(Qt.AlignCenter)

        caller_label = QLabel(f"<b>{self.caller}</b> 正在呼叫你")
        caller_label.setStyleSheet("font-size: 14pt;")
        caller_label.setAlignment(Qt.AlignCenter)

        self.time_label = QLabel("30秒后自动拒绝")
        self.time_label.setAlignment(Qt.AlignCenter)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.accept_btn = QPushButton("接听")
        self.accept_btn.setObjectName("acceptButton")
        self.accept_btn.setMinimumHeight(40)
        self.accept_btn.setCursor(Qt.PointingHandCursor)
        self.accept_btn.clicked.connect(self.on_accept)

        self.reject_btn = QPushButton("拒绝")
        self.reject_btn.setObjectName("rejectButton")
        self.reject_btn.setMinimumHeight(40)
        self.reject_btn.setCursor(Qt.PointingHandCursor)
        self.reject_btn.clicked.connect(self.on_reject)

        btn_layout.addWidget(self.accept_btn)
        btn_layout.addWidget(self.reject_btn)

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


if __name__ == '__main__':
    app = QApplication(sys.argv)

    if not check_network_config():
        sys.exit(1)

    win = LoginWindow()
    win.show()
    sys.exit(app.exec_())