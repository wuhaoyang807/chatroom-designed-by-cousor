import sys
import socket
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
                             QListWidget, QMessageBox, QInputDialog, QListWidgetItem, QTabWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QMovie, QColor
import os

# 服务器配置
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 12345

EMOJI_DIR = os.path.join(os.path.dirname(__file__), 'resources')


class ClientThread(QThread):
    message_received = pyqtSignal(str)
    connection_lost = pyqtSignal()

    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self.running = True

    def run(self):
        while self.running:
            try:
                data = self.sock.recv(4096)
                if not data:
                    print("服务器连接断开")
                    self.connection_lost.emit()
                    break
                self.message_received.emit(data.decode('utf-8'))
            except ConnectionResetError:
                print("连接被重置")
                self.connection_lost.emit()
                break
            except Exception as e:
                print(f"接收消息出错: {e}")
                self.connection_lost.emit()
                break

    def stop(self):
        self.running = False
        self.quit()
        self.wait()


def excepthook(type, value, traceback):
    QMessageBox.critical(None, '未捕获异常', str(value))
    sys.__excepthook__(type, value, traceback)


sys.excepthook = excepthook


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('登录/注册')
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
        self.login_btn.clicked.connect(self.login)
        self.reg_btn.clicked.connect(self.register)
        layout.addWidget(QLabel('用户名:'))
        layout.addWidget(self.user_edit)
        layout.addWidget(QLabel('密码:'))
        layout.addWidget(self.pwd_edit)
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.login_btn)
        btn_layout.addWidget(self.reg_btn)
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
        layout = QHBoxLayout()
        self.setLayout(layout)
        self.setWindowFlags(self.windowFlags() | Qt.Tool)
        self.load_emojis(layout)

    def load_emojis(self, layout):
        if not os.path.exists(EMOJI_DIR):
            return
        for fname in os.listdir(EMOJI_DIR):
            if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                btn = QPushButton()
                btn.setIcon(QIcon(os.path.join(EMOJI_DIR, fname)))
                btn.setIconSize(QPixmap(os.path.join(EMOJI_DIR, fname)).size())
                btn.setFixedSize(40, 40)
                btn.clicked.connect(lambda _, f=fname: self.emoji_selected.emit(f))
                layout.addWidget(btn)


class MainWindow(QWidget):
    def __init__(self, sock, username):
        try:
            super().__init__()
            self.sock = sock
            self.username = username
            self.setWindowTitle(f'聊天 - {username}')
            self.current_friend = None
            self.friends = []
            self.friend_status = {}
            self.current_group = None
            self.groups = []
            self.group_status = {}
            self.selecting_group = False  # 防重入
            self.unread_groups = set()  # 新增：未读群聊消息集合

            # 添加表情缓存
            self.emoji_cache = {}
            self.preload_emojis()  # 预加载表情

            self.init_ui()
            self.client_thread = ClientThread(self.sock)
            self.client_thread.message_received.connect(self.on_message)
            self.client_thread.connection_lost.connect(self.on_connection_lost)
            self.client_thread.start()

            # 启动定时器，确保登录后刷新群聊列表
            self.refresh_timer = QTimer(self)
            self.refresh_timer.timeout.connect(self.initial_refresh)
            self.refresh_timer.setSingleShot(True)
            self.refresh_timer.start(500)  # 延迟500毫秒刷新
        except Exception as e:
            QMessageBox.critical(None, '错误', f'主窗口初始化异常: {e}')

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
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText('输入消息...')
        self.send_btn = QPushButton('发送')
        self.send_btn.clicked.connect(self.send_message)
        self.emoji_btn = QPushButton('😀')
        self.emoji_btn.setFixedWidth(40)
        self.emoji_btn.clicked.connect(self.open_emoji_dialog)
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.emoji_btn)
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
        self.anon_nick = None

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
        # 获取私聊历史记录
        self.get_private_history()

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
            print(f"收到消息: {data}")  # 添加调试输出
            parts = data.split('|')
            cmd = parts[0]

            # 处理私聊历史记录
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
        except Exception as e:
            print(f"处理消息时出错: {e}, 消息内容: {data}")

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
            self.sock.send('LOGOUT|'.encode('utf-8'))
        except Exception:
            pass
        self.client_thread.stop()
        self.sock.close()
        event.accept()

    def initial_refresh(self):
        """登录后初始化刷新好友和群聊列表"""
        try:
            self.get_friends()
            self.get_groups()
        except Exception as e:
            print(f"初始化刷新出错: {e}")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = LoginWindow()
    win.show()
    sys.exit(app.exec_())