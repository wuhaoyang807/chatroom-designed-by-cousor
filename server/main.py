import socket
import threading
import csv
import hashlib
import os
import time
import shutil
import threading
import json

# 服务器配置
HOST = '0.0.0.0'
PORT = 12345
UDP_PORT = 12346  # 为语音通话添加UDP端口
FILE_PORT = 12347  # 专用文件传输端口
USER_CSV = 'users.csv'
FRIENDSHIP_CSV = 'friendships.csv'
GROUP_CSV = 'groups.csv'
GROUP_MEMBERS_CSV = 'group_members.csv'
DEBUG_CALL = True  # 添加调试标志
USER_FILES_DIR = 'user_files'
os.makedirs(USER_FILES_DIR, exist_ok=True)

# 文件传输相关配置
FILES_DIR = os.path.join(os.path.dirname(__file__), 'files')
os.makedirs(FILES_DIR, exist_ok=True)

# 文件传输服务器
file_transfer_server = None


# 确保CSV文件存在
def ensure_csv(file_path, header):
    if not os.path.exists(file_path):
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)


ensure_csv(USER_CSV, ['username', 'password_hash'])
ensure_csv(FRIENDSHIP_CSV, ['user_a', 'user_b'])
ensure_csv(GROUP_CSV, ['group_id', 'group_name'])
ensure_csv(GROUP_MEMBERS_CSV, ['group_id', 'username'])

clients = {}  # username: conn
active_calls = {}  # 跟踪活跃的语音通话: {username: (partner, udp_addr)}
udp_addresses = {}  # 用户UDP地址映射: {username: (ip, port)}
lock = threading.Lock()

# 创建UDP套接字用于语音数据传输
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_socket.bind((HOST, UDP_PORT))


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def register_user(username, password):
    with lock:
        with open(USER_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['username'] == username:
                    return False, 'Username already exists.'
        with open(USER_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([username, hash_password(password)])
        return True, 'Registration successful.'


def authenticate_user(username, password):
    with open(USER_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['username'] == username and row['password_hash'] == hash_password(password):
                return True
    return False


def add_friend(user_a, user_b):
    if user_a == user_b:
        return False, 'Cannot add yourself as a friend.'
    # 检查用户是否存在
    users = set()
    with open(USER_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            users.add(row['username'])
    if user_b not in users:
        return False, 'User does not exist.'
    # 检查是否已是好友
    with lock:
        with open(FRIENDSHIP_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row['user_a'] == user_a and row['user_b'] == user_b) or (
                        row['user_a'] == user_b and row['user_b'] == user_a):
                    return False, 'Already friends.'
        with open(FRIENDSHIP_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([user_a, user_b])
        return True, 'Friend added.'


def del_friend(user_a, user_b):
    changed = False
    with lock:
        rows = []
        with open(FRIENDSHIP_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row['user_a'] == user_a and row['user_b'] == user_b) or (
                        row['user_a'] == user_b and row['user_b'] == user_a):
                    changed = True
                    continue
                rows.append(row)
        with open(FRIENDSHIP_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['user_a', 'user_b'])
            writer.writeheader()
            writer.writerows(rows)
    return changed, 'Friend deleted.' if changed else 'Not friends.'


def delete_user(username, password):
    # 删除 users.csv 中指定用户名和密码的行
    deleted = False
    with lock:
        rows = []
        with open(USER_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['username'] == username and row['password_hash'] == hash_password(password):
                    deleted = True
                    continue
                rows.append(row)
        if deleted:
            with open(USER_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['username', 'password_hash'])
                writer.writeheader()
                writer.writerows(rows)
    return deleted


def get_friends(username):
    friends = set()
    with open(FRIENDSHIP_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['user_a'] == username:
                friends.add(row['user_b'])
            elif row['user_b'] == username:
                friends.add(row['user_a'])
    return list(friends)


def get_friends_with_status(username):
    friends = []
    with open(FRIENDSHIP_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['user_a'] == username:
                friends.append(row['user_b'])
            elif row['user_b'] == username:
                friends.append(row['user_a'])
    # 返回 [(friend, online_status)]
    with lock:
        return [(f, f in clients) for f in friends]


def notify_friends_status(username, online):
    friends = get_friends(username)
    with lock:
        for f in friends:
            if f in clients:
                try:
                    if online:
                        send_msg(clients[f], f'FRIEND_ONLINE|{username}')
                    else:
                        send_msg(clients[f], f'FRIEND_OFFLINE|{username}')
                except Exception:
                    pass


# UDP音频服务已移除，现在使用P2P直连通信
# 保留UDP socket用于兼容性，但不再处理音频中继
def handle_udp_audio():
    print(f"UDP服务开始监听 {HOST}:{UDP_PORT} (仅用于兼容性)")
    while True:
        try:
            # 简单的UDP监听，不处理音频数据
            data, addr = udp_socket.recvfrom(1024)
            # 记录收到的数据但不处理
            if len(data) > 0:
                print(f"收到UDP数据来自 {addr}，长度: {len(data)} (已忽略)")
        except Exception as e:
            print(f"UDP监听异常: {e}")
            time.sleep(1)


def send_msg(conn, msg):
    if not msg.endswith('\n'):
        msg += '\n'
    conn.send(msg.encode('utf-8'))


class FileTransfer:
    CHUNK_SIZE = 1024 * 1024  # 1MB per chunk
    MAX_RETRIES = 3

    @staticmethod
    def calculate_file_hash(file_path):
        """计算文件的MD5哈希值"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    @staticmethod
    def save_file_chunk(file_path, chunk_id, chunk_data):
        """保存文件块到临时文件"""
        chunk_dir = os.path.join(os.path.dirname(file_path), '.chunks')
        os.makedirs(chunk_dir, exist_ok=True)
        chunk_path = os.path.join(chunk_dir, f'{os.path.basename(file_path)}.chunk{chunk_id}')
        with open(chunk_path, 'wb') as f:
            f.write(chunk_data)

    @staticmethod
    def get_file_chunk(file_path, chunk_id):
        """获取文件块"""
        with open(file_path, 'rb') as f:
            f.seek(chunk_id * FileTransfer.CHUNK_SIZE)
            return f.read(FileTransfer.CHUNK_SIZE)

    @staticmethod
    def cleanup_chunks(file_path):
        """清理临时文件块"""
        chunk_dir = os.path.join(os.path.dirname(file_path), '.chunks')
        if os.path.exists(chunk_dir):
            shutil.rmtree(chunk_dir)


def get_user_file_dir(user1, user2):
    """获取两个用户之间的文件存储目录"""
    users = sorted([user1, user2])
    dir_path = os.path.join(FILES_DIR, f'{users[0]}__{users[1]}')
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


def handle_file_upload(conn, from_user, to_user, fname, file_size, total_chunks):
    """通知客户端使用专用文件传输连接"""
    try:
        # 发送重定向指令，告知客户端使用专用端口
        redirect_msg = f'USE_FILE_PORT|{FILE_PORT}|{from_user}|{to_user}|{fname}|{file_size}'
        conn.send(redirect_msg.encode('utf-8'))
        print(f"已通知客户端使用专用文件传输端口: {FILE_PORT}")
    except Exception as e:
        print(f"通知客户端使用专用文件端口出错: {e}")
        conn.send(f'ERROR|{str(e)}'.encode('utf-8'))


def handle_file_download(conn, from_user, to_user, fname):
    """通知客户端使用专用文件传输连接"""
    try:
        # 发送重定向指令，告知客户端使用专用端口
        redirect_msg = f'USE_FILE_PORT|{FILE_PORT}|{from_user}|{to_user}|{fname}'
        conn.send(redirect_msg.encode('utf-8'))
        print(f"已通知客户端使用专用文件传输端口: {FILE_PORT}")
    except Exception as e:
        print(f"通知客户端使用专用文件端口出错: {e}")
        conn.send(f'ERROR|{str(e)}'.encode('utf-8'))


def handle_client(conn, addr):
    username = None
    try:
        while True:
            try:
                data = conn.recv(4096).decode('utf-8')
                if not data:
                    print(f"客户端 {addr} 连接关闭")
                    break

                parts = data.split('|')
                cmd = parts[0]
                # 健壮性检查
                if not cmd:
                    continue

                if cmd == 'REGISTER':
                    _, u, p = parts
                    success, msg = register_user(u, p)
                    send_msg(conn, f'REGISTER_RESULT|{"OK" if success else "FAIL"}|{msg}')
                elif cmd == 'LOGIN':
                    _, u, p = parts
                    if authenticate_user(u, p):
                        # 检查用户是否已经登录，如果是，则断开前一个连接
                        with lock:
                            if u in clients:
                                try:
                                    # 尝试向旧连接发送下线通知
                                    try:
                                        send_msg(clients[u], 'FORCE_LOGOUT|另一个客户端登录了您的账号')
                                    except:
                                        pass
                                    # 关闭旧连接
                                    try:
                                        clients[u].close()
                                    except:
                                        pass
                                    print(f"用户 {u} 的旧连接已被强制下线")
                                except Exception as e:
                                    print(f"强制下线旧连接异常: {e}")

                            # 更新连接信息
                            clients[u] = conn

                        username = u
                        send_msg(conn, 'LOGIN_RESULT|OK|Login successful.')
                        notify_friends_status(username, True)
                    else:
                        send_msg(conn, 'LOGIN_RESULT|FAIL|Invalid username or password.')
                elif cmd == 'ADD_FRIEND':
                    _, u, f = parts
                    success, msg = add_friend(u, f)
                    send_msg(conn, f'ADD_FRIEND_RESULT|{"OK" if success else "FAIL"}|{msg}')
                elif cmd == 'DEL_FRIEND':
                    _, u, f = parts
                    success, msg = del_friend(u, f)
                    send_msg(conn, f'DEL_FRIEND_RESULT|{"OK" if success else "FAIL"}|{msg}')
                elif cmd == 'DELETE_USER':
                    # DELETE_USER|username|password
                    _, u, p = parts
                    success = delete_user(u, p)
                    send_msg(conn, f'DELETE_USER_RESULT|{"OK" if success else "FAIL"}')
                elif cmd == 'GET_FRIENDS':
                    _, u = parts[:2]
                    friends_status = get_friends_with_status(u)
                    # 格式 FRIEND_LIST|user1:online|user2:offline|...
                    friend_strs = [f"{f}:{'online' if online else 'offline'}" for f, online in friends_status]
                    send_msg(conn, f"FRIEND_LIST|{'|'.join(friend_strs)}")
                elif cmd == 'MSG':
                    # MSG|to_user|message
                    _, to_user, msg = parts
                    # 只允许发给好友
                    if to_user not in get_friends(username):
                        send_msg(conn, f'ERROR|You are not friends with {to_user}.')
                    else:
                        # 保存消息历史
                        save_private_message(username, to_user, msg)

                        with lock:
                            if to_user in clients:
                                send_msg(clients[to_user], f'MSG|{username}|{msg}')
                            else:
                                send_msg(conn, f'ERROR|User {to_user} not online.')
                elif cmd == 'EMOJI':
                    # EMOJI|to_user|emoji_id
                    _, to_user, emoji_id = parts
                    if to_user not in get_friends(username):
                        send_msg(conn, f'ERROR|You are not friends with {to_user}.')
                    else:
                        # 保存表情消息历史
                        save_private_message(username, to_user, f"[EMOJI]{emoji_id}")

                        with lock:
                            if to_user in clients:
                                send_msg(clients[to_user], f'EMOJI|{username}|{emoji_id}')
                            else:
                                send_msg(conn, f'ERROR|User {to_user} not online.')
                # 处理语音通话请求
                elif cmd == 'CALL_REQUEST':
                    # CALL_REQUEST|from_user|to_user|udp_port
                    _, from_user, to_user, udp_port = parts
                    if DEBUG_CALL:
                        print(f"===== CALL REQUEST DEBUG =====")
                        print(f"  从 {from_user} 到 {to_user}")
                        print(f"  客户端IP: {addr[0]}, UDP端口: {udp_port}")
                        print(f"  当前在线用户: {list(clients.keys())}")
                        print(f"  to_user在clients中: {to_user in clients}")
                        print(f"  to_user在active_calls中: {to_user in active_calls}")

                    if to_user not in get_friends(from_user):
                        if DEBUG_CALL:
                            print(f"  错误: {to_user} 不是 {from_user} 的好友")
                        send_msg(conn, f'ERROR|You are not friends with {to_user}.')
                    else:
                        client_ip = addr[0]
                        client_udp_port = int(udp_port)
                        print(f"收到语音通话请求: {from_user} -> {to_user}, UDP: {client_ip}:{client_udp_port}")

                        # 保存发起者的UDP地址（使用客户端的真实外网IP）
                        with lock:
                            udp_addresses[from_user] = (client_ip, client_udp_port)

                            # 检查对方是否在线
                            if to_user in clients:
                                to_user_conn = clients[to_user]
                                # 验证连接是否有效
                                try:
                                    # 简单测试连接是否有效
                                    error_test = to_user_conn.fileno()
                                    if error_test < 0:
                                        raise Exception("Invalid socket descriptor")

                                    # 检查对方是否已经在通话中
                                    if to_user in active_calls:
                                        if DEBUG_CALL:
                                            print(f"  目标用户 {to_user} 已在通话中")
                                        send_msg(conn, f'CALL_RESPONSE|BUSY|{to_user}')
                                    else:
                                        # 将通话请求转发给对方，包含发起者的外网IP
                                        try:
                                            if DEBUG_CALL:
                                                print(f"  发送CALL_INCOMING到 {to_user}")
                                                print(f"  clients[{to_user}] 是否有效: {clients[to_user] is not None}")

                                            # 发送通话请求消息，包含发起者的外网IP和端口
                                            send_msg(to_user_conn, f'CALL_INCOMING|{from_user}|{client_ip}|{client_udp_port}')

                                            # 发送确认到发起方
                                            send_msg(conn, f'CALL_RESPONSE|SENDING|{to_user}')

                                            # 通知发起方对方已经收到通话请求
                                            if DEBUG_CALL:
                                                print(f"  CALL_INCOMING已发送，对方应该收到请求")
                                        except Exception as e:
                                            if DEBUG_CALL:
                                                print(f"  发送CALL_INCOMING失败: {e}")
                                            # 从客户端列表中移除无效连接
                                            del clients[to_user]
                                            send_msg(conn, f'CALL_RESPONSE|ERROR|{to_user}|{str(e)}')
                                except Exception as e:
                                    if DEBUG_CALL:
                                        print(f"  连接错误: {e}")
                                    # 连接无效，从客户端列表中移除
                                    del clients[to_user]
                                    send_msg(conn, f'CALL_RESPONSE|OFFLINE|{to_user}')
                            else:
                                if DEBUG_CALL:
                                    print(f"  目标用户 {to_user} 不在线")
                                send_msg(conn, f'CALL_RESPONSE|OFFLINE|{to_user}')
                    if DEBUG_CALL:
                        print("===== CALL REQUEST DEBUG END =====")
                elif cmd == 'CALL_ACCEPT':
                    # CALL_ACCEPT|from_user|to_user|udp_port
                    try:
                        if len(parts) < 4:
                            print(f"CALL_ACCEPT消息格式错误: {data}")
                            return

                        _, from_user, to_user, udp_port = parts
                        if DEBUG_CALL:
                            print(f"===== CALL ACCEPT DEBUG =====")
                            print(f"  从 {from_user} 接受 {to_user} 的通话")
                            print(f"  客户端IP: {addr[0]}, UDP端口: {udp_port}")
                            print(f"  当前在线用户: {list(clients.keys())}")
                            print(f"  to_user在clients中: {to_user in clients}")

                        client_ip = addr[0]
                        client_udp_port = int(udp_port)
                        print(f"接受语音通话: {from_user} -> {to_user}, UDP: {client_ip}:{client_udp_port}")

                        with lock:
                            # 保存接受者的UDP地址（使用客户端的真实外网IP）
                            udp_addresses[from_user] = (client_ip, client_udp_port)

                            # 记录通话状态 - 修复：确保双方都有正确的对方地址
                            if to_user in udp_addresses:
                                # 发起方的地址
                                caller_addr = udp_addresses[to_user]
                                active_calls[from_user] = (to_user, caller_addr)
                                active_calls[to_user] = (from_user, (client_ip, client_udp_port))
                                
                                # 向双方发送连接信息
                                if to_user in clients:
                                    try:
                                        # 向发起方发送接受者的外网地址信息
                                        accept_msg = f'CALL_ACCEPTED|{from_user}|{client_ip}|{client_udp_port}'
                                        send_msg(clients[to_user], accept_msg)
                                        if DEBUG_CALL:
                                            print(f"  发送CALL_ACCEPTED给发起方 {to_user}: {accept_msg}")
                                    except Exception as e:
                                        if DEBUG_CALL:
                                            print(f"  发送CALL_ACCEPTED失败: {e}")
                                        del clients[to_user]  # 清理无效连接
                                
                                # 向接受方发送发起方的外网地址信息
                                if from_user in clients:
                                    try:
                                        caller_ip, caller_port = caller_addr
                                        connect_msg = f'CALL_CONNECT_INFO|{to_user}|{caller_ip}|{caller_port}'
                                        send_msg(clients[from_user], connect_msg)
                                        if DEBUG_CALL:
                                            print(f"  发送CALL_CONNECT_INFO给接受方 {from_user}: {connect_msg}")
                                    except Exception as e:
                                        if DEBUG_CALL:
                                            print(f"  发送CALL_CONNECT_INFO失败: {e}")
                            else:
                                if DEBUG_CALL:
                                    print(f"  错误: 发起方 {to_user} 的UDP地址未找到")
                                # 通知接受方连接失败
                                if from_user in clients:
                                    send_msg(clients[from_user], f'CALL_RESPONSE|ERROR|发起方地址未找到')

                        if DEBUG_CALL:
                            print("===== CALL ACCEPT DEBUG END =====")
                    except Exception as e:
                        print(f"处理CALL_ACCEPT出错: {e}")
                        if DEBUG_CALL:
                            print(f"  错误详情: {str(e)}")
                elif cmd == 'CALL_REJECT':
                    # CALL_REJECT|from_user|to_user
                    _, from_user, to_user = parts
                    print(f"拒绝语音通话: {from_user} -> {to_user}")

                    with lock:
                        # 转发拒绝消息给发起者
                        if to_user in clients:
                            send_msg(clients[to_user], f'CALL_REJECTED|{from_user}')
                elif cmd == 'CALL_END':
                    # CALL_END|from_user|to_user
                    _, from_user, to_user = parts
                    print(f"结束语音通话: {from_user} -> {to_user}")

                    with lock:
                        # 清除通话记录
                        if from_user in active_calls:
                            del active_calls[from_user]

                        # 发送通话结束消息给对方
                        if to_user in clients and to_user in active_calls:
                            send_msg(clients[to_user], f'CALL_ENDED|{from_user}')
                            del active_calls[to_user]
                elif cmd == 'UDP_PORT_UPDATE':
                    # UDP_PORT_UPDATE|username|udp_port
                    _, user, udp_port = parts
                    client_ip = addr[0]
                    client_udp_port = int(udp_port)

                    with lock:
                        udp_addresses[user] = (client_ip, client_udp_port)
                        print(f"更新用户UDP地址: {user} -> {client_ip}:{client_udp_port}")
                elif cmd == 'LOGOUT':
                    break
                elif cmd == 'CREATE_GROUP':
                    _, u, group_name = parts
                    success, msg, group_id = create_group(group_name)
                    if success:
                        join_group(group_id, u)
                    send_msg(conn, f'CREATE_GROUP_RESULT|{"OK" if success else "FAIL"}|{msg}|{group_id}')
                elif cmd == 'JOIN_GROUP':
                    _, u, group_id = parts
                    success, msg = join_group(group_id, u)
                    send_msg(conn, f'JOIN_GROUP_RESULT|{"OK" if success else "FAIL"}|{msg}|{group_id}')
                elif cmd == 'GET_GROUPS':
                    _, u = parts[:2]
                    groups = get_user_groups(u)
                    # 格式 GROUP_LIST|group_id:group_name|...
                    group_strs = [f'{gid}:{gname}' for gid, gname in groups]
                    send_msg(conn, f'GROUP_LIST|{"|".join(group_strs)}')
                elif cmd == 'GET_GROUP_MEMBERS':
                    _, group_id = parts[:2]
                    members = get_group_members(group_id)
                    send_msg(conn, f'GROUP_MEMBERS|{"|".join(members)}')
                elif cmd == 'GROUP_MSG':
                    # GROUP_MSG|group_id|from_user|msg
                    try:
                        if len(parts) < 3:
                            print(f"群聊消息格式错误: {data}")
                            continue

                        _, group_id, from_user = parts[:3]
                        msg = '|'.join(parts[3:])  # 正确获取消息内容

                        print(f"处理群聊消息: group_id={group_id}, from_user={from_user}, msg={msg}")

                        members = get_group_members(group_id)
                        print(f'群聊广播: group_id={group_id}, members={members}')
                        save_group_message(group_id, from_user, msg)
                        with lock:
                            for m in members:
                                if m in clients:
                                    try:
                                        # 发送消息时，带上发送者的在线状态信息
                                        send_msg(clients[m], f'GROUP_MSG|{str(int(group_id))}|{from_user}|{msg}')
                                        # 如果消息接收者与发送者是好友关系，通知发送者在线
                                        if m != from_user and from_user in get_friends(m):
                                            send_msg(clients[m], f'FRIEND_ONLINE|{from_user}')
                                    except Exception as e:
                                        print(f'发送给{m}失败: {e}')
                    except Exception as e:
                        print(f"处理群聊消息出错: {e}, 原始数据: {data}")

                elif cmd == 'GROUP_MSG_ANON':
                    # GROUP_MSG_ANON|group_id|anon_nick|msg
                    try:
                        if len(parts) < 3:
                            print(f"匿名群聊消息格式错误: {data}")
                            continue

                        _, group_id, anon_nick = parts[:3]
                        msg = '|'.join(parts[3:])  # 正确获取消息内容

                        print(f"处理匿名群聊消息: group_id={group_id}, anon_nick={anon_nick}, msg={msg}")

                        members = get_group_members(group_id)
                        print(f'匿名群聊广播: group_id={group_id}, members={members}')
                        save_group_message(group_id, None, msg, anon_nick=anon_nick)
                        with lock:
                            for m in members:
                                if m in clients:
                                    try:
                                        send_msg(clients[m], f'GROUP_MSG_ANON|{str(int(group_id))}|{anon_nick}|{msg}')
                                    except Exception as e:
                                        print(f'发送给{m}失败: {e}')
                    except Exception as e:
                        print(f"处理匿名群聊消息出错: {e}, 原始数据: {data}")
                elif cmd == 'GET_GROUP_HISTORY':
                    try:
                        _, group_id = parts[:2]
                        print(f"获取群聊历史: group_id={group_id}")
                        history = get_group_history(group_id)
                        # 格式 GROUP_HISTORY|type|sender|msg|...
                        resp = ['GROUP_HISTORY']
                        for row in history:
                            resp.extend(row)
                        response_str = '|'.join(resp)
                        print(f"发送群聊历史: {len(history)}条消息")
                        send_msg(conn, response_str)
                    except Exception as e:
                        print(f"处理群聊历史请求出错: {e}")
                        send_msg(conn, 'GROUP_HISTORY|error|获取群聊历史失败')
                elif cmd == 'GET_PRIVATE_HISTORY':
                    # GET_PRIVATE_HISTORY|from_user|to_user
                    _, from_user, to_user = parts
                    if to_user not in get_friends(from_user):
                        send_msg(conn, 'PRIVATE_HISTORY|error|不是好友关系')
                    else:
                        try:
                            history = get_private_history(from_user, to_user)
                            # 格式 PRIVATE_HISTORY|sender1|msg1|sender2|msg2|...
                            resp = ['PRIVATE_HISTORY']
                            for row in history:
                                resp.extend(row)
                            response_str = '|'.join(resp)
                            send_msg(conn, response_str)
                        except Exception as e:
                            print(f"获取私聊历史出错: {e}")
                            send_msg(conn, 'PRIVATE_HISTORY|error|获取历史记录失败')
                elif cmd == 'FILE_UPLOAD_START':
                    # 新的文件上传处理
                    from_user = parts[1]
                    to_user = parts[2]
                    fname = parts[3]
                    file_size = int(parts[4])
                    total_chunks = int(parts[5])
                    handle_file_upload(conn, from_user, to_user, fname, file_size, total_chunks)

                elif cmd == 'FILE_DOWNLOAD_START':
                    # 新的文件下载处理
                    from_user = parts[1]
                    to_user = parts[2]
                    fname = parts[3]
                    handle_file_download(conn, from_user, to_user, fname)

                elif cmd == 'FILE_LIST':
                    # FILE_LIST|from_user|to_user
                    _, from_user, to_user = parts
                    user_dir = get_user_file_dir(from_user, to_user)
                    if os.path.exists(user_dir):
                        files = os.listdir(user_dir)
                    else:
                        files = []
                    send_msg(conn, 'FILE_LIST|' + '|'.join(files))
                elif cmd == 'PING':
                    # 响应客户端的PING请求以保持连接
                    send_msg(conn, 'PONG')
                else:
                    send_msg(conn, 'ERROR|Unknown command.')
            except Exception as e:
                print(f"处理客户端 {addr} 命令出错: {e}")
                continue
    except Exception as e:
        print(f"客户端处理总体错误: {e}")
    finally:
        if username:
            with lock:
                if username in clients:
                    del clients[username]
                # 清理用户的通话状态
                if username in active_calls:
                    partner = active_calls[username][0]
                    del active_calls[username]
                    # 通知通话伙伴通话已结束
                    if partner in clients and partner in active_calls:
                        send_msg(clients[partner], f'CALL_ENDED|{username}')
                        del active_calls[partner]
                # 清理UDP地址映射
                if username in udp_addresses:
                    del udp_addresses[username]
            notify_friends_status(username, False)
        try:
            conn.close()
        except:
            pass
        print(f'连接 {addr} 已关闭')


def start_server():
    global file_transfer_server

    print(f'Server listening on {HOST}:{PORT} (TCP) and {HOST}:{UDP_PORT} (UDP)')

    # 启动UDP音频处理线程
    udp_thread = threading.Thread(target=handle_udp_audio, daemon=True)
    udp_thread.start()

    # 启动文件传输服务器
    file_transfer_server = FileTransferServer(HOST, FILE_PORT)
    file_transfer_server.start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        while True:
            try:
                conn, addr = s.accept()
                threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                print(f"接受连接错误: {e}")
                time.sleep(1)  # 避免CPU空转


def get_next_group_id():
    max_id = 0
    with open(GROUP_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                gid = int(row['group_id'])
                if gid > max_id:
                    max_id = gid
            except Exception:
                continue
    return str(max_id + 1)


def create_group(group_name):
    with lock:
        with open(GROUP_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['group_name'] == group_name:
                    return False, 'Group name exists.', row['group_id']
        group_id = get_next_group_id()
        with open(GROUP_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([group_id, group_name])
    return True, 'Group created.', group_id


def join_group(group_id, username):
    with lock:
        # 检查是否已在群中
        found = False
        with open(GROUP_MEMBERS_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['group_id'] == group_id and row['username'] == username:
                    found = True
                    break
        if not found:
            with open(GROUP_MEMBERS_CSV, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([group_id, username])
    return True, 'Joined group.'


def get_user_groups(username):
    group_ids = set()
    with open(GROUP_MEMBERS_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['username'] == username:
                group_ids.add(row['group_id'])
    groups = []
    with open(GROUP_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['group_id'] in group_ids:
                groups.append((row['group_id'], row['group_name']))
    return groups


def get_group_members(group_id):
    group_id = str(int(group_id))  # 统一格式，去除前导零
    members = []
    with open(GROUP_MEMBERS_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if str(int(row['group_id'])) == group_id:
                members.append(row['username'])
    return members


def save_group_message(group_id, sender, msg, anon_nick=None):
    fname = f'group_{group_id}_history.csv'
    with open(fname, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if anon_nick:
            writer.writerow(['anon', anon_nick, msg])
        else:
            writer.writerow(['user', sender, msg])


def get_group_history(group_id):
    fname = f'group_{group_id}_history.csv'
    if not os.path.exists(fname):
        return []
    history = []
    with open(fname, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            history.append(row)
    return history


def save_private_message(sender, receiver, msg):
    """保存私聊消息历史"""
    # 使用字典序排序确保两个用户之间的消息保存在同一个文件中
    users = sorted([sender, receiver])
    fname = f'private_{users[0]}_{users[1]}_history.csv'
    with open(fname, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([sender, msg])


def get_private_history(user1, user2):
    """获取两个用户之间的私聊历史记录"""
    users = sorted([user1, user2])
    fname = f'private_{users[0]}_{users[1]}_history.csv'
    if not os.path.exists(fname):
        return []
    history = []
    with open(fname, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            history.append(row)
    return history


# 文件传输服务
class FileTransferServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.socket.listen(5)
        self.running = True
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        print(f"文件传输服务器开始监听 {host}:{port}")

    def start(self):
        self.thread.start()

    def run(self):
        while self.running:
            try:
                client_socket, addr = self.socket.accept()
                client_handler = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, addr)
                )
                client_handler.daemon = True
                client_handler.start()
            except Exception as e:
                print(f"接受文件传输连接错误: {e}")
                time.sleep(1)  # 避免CPU空转

    def handle_client(self, client_socket, addr):
        print(f"新文件传输连接: {addr}")
        try:
            # 接收登录凭证和请求类型
            auth_data = client_socket.recv(1024).decode('utf-8')
            parts = auth_data.split('|')
            if len(parts) < 3:
                client_socket.send('ERROR|Invalid request format'.encode('utf-8'))
                client_socket.close()
                return

            request_type = parts[0]
            username = parts[1]

            if request_type == 'UPLOAD':
                # UPLOAD|username|to_user|filename|filesize
                if len(parts) < 5:
                    client_socket.send('ERROR|Invalid upload request'.encode('utf-8'))
                    client_socket.close()
                    return

                to_user = parts[2]
                filename = parts[3]
                filesize = int(parts[4])

                # 检查接收者是否是发送者的好友
                if not self.is_friend(username, to_user):
                    client_socket.send('ERROR|Not friends'.encode('utf-8'))
                    client_socket.close()
                    return

                self.handle_upload(client_socket, username, to_user, filename, filesize)

            elif request_type == 'DOWNLOAD':
                # DOWNLOAD|username|from_user|filename
                if len(parts) < 4:
                    client_socket.send('ERROR|Invalid download request'.encode('utf-8'))
                    client_socket.close()
                    return

                from_user = parts[2]
                filename = parts[3]

                # 检查请求者是否是文件所有者的好友
                if not self.is_friend(username, from_user):
                    client_socket.send('ERROR|Not friends'.encode('utf-8'))
                    client_socket.close()
                    return

                self.handle_download(client_socket, username, from_user, filename)

            else:
                client_socket.send('ERROR|Unknown request type'.encode('utf-8'))
                client_socket.close()

        except Exception as e:
            print(f"文件传输处理错误: {e}")
            try:
                client_socket.send(f'ERROR|{str(e)}'.encode('utf-8'))
            except:
                pass
            finally:
                client_socket.close()

    def is_friend(self, user1, user2):
        """检查两个用户是否是好友"""
        try:
            with open(FRIENDSHIP_CSV, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (row['user_a'] == user1 and row['user_b'] == user2) or \
                            (row['user_a'] == user2 and row['user_b'] == user1):
                        return True
            return False
        except Exception as e:
            print(f"检查好友关系错误: {e}")
            return False

    def handle_upload(self, client_socket, from_user, to_user, filename, filesize):
        """处理文件上传"""
        file_path = None
        try:
            # 获取存储目录
            file_dir = get_user_file_dir(from_user, to_user)
            file_path = os.path.join(file_dir, filename)

            # 检查文件是否已存在，如果存在则添加时间戳
            if os.path.exists(file_path):
                base, ext = os.path.splitext(filename)
                timestamp = int(time.time())
                filename = f"{base}_{timestamp}{ext}"
                file_path = os.path.join(file_dir, filename)

            # 通知客户端准备好接收
            client_socket.send(f'READY|{filename}'.encode('utf-8'))

            # 接收文件数据
            received = 0
            with open(file_path, 'wb') as f:
                while received < filesize:
                    chunk = client_socket.recv(min(8192, filesize - received))
                    if not chunk:
                        raise Exception("Connection closed during upload")
                    f.write(chunk)
                    received += len(chunk)
                    # 发送进度更新
                    if received % (1024 * 1024) == 0 or received == filesize:  # 每1MB或完成时更新
                        progress = min(100, int(received * 100 / filesize))
                        try:
                            client_socket.send(f'PROGRESS|{progress}'.encode('utf-8'))
                        except:
                            pass

            # 发送成功消息
            client_socket.send('SUCCESS'.encode('utf-8'))
            print(f"文件上传成功: {filename}, 大小: {filesize}字节, 从 {from_user} 到 {to_user}")

        except Exception as e:
            print(f"文件上传错误: {e}")
            try:
                client_socket.send(f'ERROR|{str(e)}'.encode('utf-8'))
            except:
                pass
            # 删除不完整的文件
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
        finally:
            client_socket.close()

    def handle_download(self, client_socket, username, from_user, filename):
        """处理文件下载"""
        try:
            # 获取文件路径
            file_dir = get_user_file_dir(from_user, username)
            file_path = os.path.join(file_dir, filename)

            if not os.path.exists(file_path):
                client_socket.send(f'ERROR|File not found: {filename}'.encode('utf-8'))
                client_socket.close()
                return

            # 获取文件大小
            filesize = os.path.getsize(file_path)

            # 发送准备就绪消息
            client_socket.send(f'READY|{filesize}'.encode('utf-8'))

            # 发送文件数据
            sent = 0
            with open(file_path, 'rb') as f:
                while sent < filesize:
                    # 读取并发送数据块
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    client_socket.sendall(chunk)
                    sent += len(chunk)
                    # 每发送1MB数据或完成时检查客户端进度确认
                    if sent % (1024 * 1024) == 0 or sent == filesize:
                        try:
                            # 设置短超时等待确认
                            client_socket.settimeout(5)
                            ack = client_socket.recv(1024).decode('utf-8')
                            if ack.startswith('ACK'):
                                progress = min(100, int(sent * 100 / filesize))
                                print(f"文件下载进度: {progress}%, {sent}/{filesize}字节")
                            else:
                                print(f"意外的客户端响应: {ack}")
                        except socket.timeout:
                            # 不因超时中断传输
                            print("等待客户端确认超时，继续传输")
                        except Exception as e:
                            print(f"检查客户端确认时出错: {e}")
                            # 继续传输而不中断
                        finally:
                            # 恢复无超时
                            client_socket.settimeout(None)

            print(f"文件下载完成: {filename}, 大小: {filesize}字节, 发送给 {username}")

        except Exception as e:
            print(f"文件下载错误: {e}")
            try:
                client_socket.send(f'ERROR|{str(e)}'.encode('utf-8'))
            except:
                pass
        finally:
            client_socket.close()

    def stop(self):
        """停止文件传输服务器"""
        self.running = False
        try:
            self.socket.close()
        except:
            pass


if __name__ == '__main__':
    start_server() 