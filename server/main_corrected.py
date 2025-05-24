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


# 处理UDP音频数据中继
def handle_udp_audio():
    print(f"UDP音频服务开始监听 {HOST}:{UDP_PORT}")
    while True:
        try:
            data, addr = udp_socket.recvfrom(65536)  # 更大的缓冲区用于音频
            # 解析头部以确定目标用户
            if len(data) < 2:  # 确保数据至少包含2字节头部
                print(f"收到无效UDP数据包(长度<2): {len(data)}字节, 来自: {addr}")
                continue

            header_len = data[0]  # 第一个字节表示头部长度
            if len(data) < header_len + 1:
                print(f"收到无效UDP数据包(头部不完整): {len(data)}字节, 头部长度: {header_len}, 来自: {addr}")
                continue

            header = data[1:header_len + 1].decode('utf-8')
            audio_data = data[header_len + 1:]
            
            # 添加额外调试信息
            print(f"收到UDP音频数据: {len(data)}字节, 音频数据: {len(audio_data)}字节, 来自: {addr}, 头部: {header}")
            
            # 头部格式：发送者|接收者
            try:
                sender, receiver = header.split('|')

                # 检查接收者是否在线和是否处于通话中
                with lock:
                    if receiver in active_calls and active_calls[receiver][0] == sender and receiver in udp_addresses:
                        target_addr = udp_addresses[receiver]
                        # 额外检查目标地址有效性
                        if target_addr[0] is None or target_addr[1] is None:
                            print(f"接收者 {receiver} 的UDP地址无效: {target_addr}")
                            continue
                        
                        print(f"转发音频数据到 {receiver}: {target_addr}, 数据大小: {len(data)}字节")
                        udp_socket.sendto(data, target_addr)
                    else:
                        print(f"无法转发音频数据: receiver={receiver}, 在active_calls中={receiver in active_calls}, "
                              f"通话对象={active_calls.get(receiver)}, 有UDP地址={receiver in udp_addresses}")
            except Exception as e:
                print(f"处理UDP音频数据出错: {e}, 头部: {header}")
        except Exception as e:
            print(f"UDP音频处理异常: {e}")


def send_msg(conn, msg):
    if not msg.endswith('\n'):
        msg += '\n'
    try:
        conn.send(msg.encode('utf-8'))
        return True
    except Exception as e:
        print(f"发送消息失败: {e}")
        return False


def save_private_message(sender, receiver, msg):
    """保存私聊消息历史"""
    try:
        # 使用字典序排序确保两个用户之间的消息保存在同一个文件中
        users = sorted([sender, receiver])
        fname = f'private_{users[0]}_{users[1]}_history.csv'
        with open(fname, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([sender, msg])
        print(f"私聊消息已保存: {fname}")
    except Exception as e:
        print(f"保存私聊消息失败: {e}")


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
                        try:
                            # 保存消息历史
                            save_private_message(username, to_user, msg)
                            print(f"保存私聊消息: {username} -> {to_user}: {msg}")
                            
                            with lock:
                                if to_user in clients:
                                    send_msg(clients[to_user], f'MSG|{username}|{msg}')
                                    print(f"转发消息给在线用户 {to_user}")
                                else:
                                    send_msg(conn, f'ERROR|User {to_user} not online.')
                                    print(f"用户 {to_user} 不在线")
                        except Exception as e:
                            print(f"处理私聊消息出错: {e}")
                            send_msg(conn, f'ERROR|发送消息失败: {e}')
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
                        try:
                            client_ip = addr[0]
                            client_udp_port = int(udp_port)
                            print(f"收到语音通话请求: {from_user} -> {to_user}, UDP: {client_ip}:{client_udp_port}")

                            # 保存发起者的UDP地址
                            with lock:
                                # 验证IP和端口
                                if client_ip in ['0.0.0.0', 'localhost', '127.0.0.1']:
                                    # 这是一个本地测试 - 使用客户端的真实外部IP
                                    client_ip = addr[0]
                                
                                if client_udp_port <= 0 or client_udp_port > 65535:
                                    raise ValueError(f"无效的UDP端口: {client_udp_port}")
                                
                                udp_addresses[from_user] = (client_ip, client_udp_port)
                                print(f"更新发起者UDP地址: {from_user} -> {client_ip}:{client_udp_port}")
                        except Exception as e:
                            print(f"处理UDP地址错误: {e}")
                            send_msg(conn, f'CALL_RESPONSE|ERROR|{to_user}|处理通话请求出错: {e}')
                            continue

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
                                    # 将通话请求转发给对方
                                    try:
                                        if DEBUG_CALL:
                                            print(f"  准备发送CALL_INCOMING到 {to_user}")
                                            print(f"  to_user_conn有效: {to_user_conn is not None}")

                                        # 发送通话请求消息
                                        call_msg = f'CALL_INCOMING|{from_user}'
                                        success = send_msg(to_user_conn, call_msg)
                                        
                                        if DEBUG_CALL:
                                            print(f"  发送CALL_INCOMING: '{call_msg}', 成功: {success}")
                                            if success:
                                                print(f"  消息长度: {len(call_msg)}字节")
                                                print(f"  连接状态: {to_user_conn.fileno()}")
                                            else:
                                                print(f"  发送失败!")

                                        if success:
                                            # 发送确认到发起方
                                            send_msg(conn, f'CALL_RESPONSE|SENDING|{to_user}')
                                            if DEBUG_CALL:
                                                print(f"  CALL_INCOMING已发送，对方应该收到请求")
                                        else:
                                            # 发送失败，从客户端列表中移除无效连接
                                            if DEBUG_CALL:
                                                print(f"  发送CALL_INCOMING失败，移除无效连接")
                                            del clients[to_user]
                                            send_msg(conn, f'CALL_RESPONSE|ERROR|{to_user}|连接无效')
                                            
                                    except Exception as e:
                                        if DEBUG_CALL:
                                            print(f"  发送CALL_INCOMING异常: {e}")
                                        # 从客户端列表中移除无效连接
                                        if to_user in clients:
                                            del clients[to_user]
                                        send_msg(conn, f'CALL_RESPONSE|ERROR|{to_user}|{str(e)}')
                            except Exception as e:
                                if DEBUG_CALL:
                                    print(f"  连接错误: {e}")
                                # 连接无效，从客户端列表中移除
                                if to_user in clients:
                                    del clients[to_user]
                                send_msg(conn, f'CALL_RESPONSE|OFFLINE|{to_user}')
                        else:
                            if DEBUG_CALL:
                                print(f"  目标用户 {to_user} 不在线")
                            send_msg(conn, f'CALL_RESPONSE|OFFLINE|{to_user}')

                    if DEBUG_CALL:
                        print("===== CALL REQUEST DEBUG END =====")
                        
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
                            print(f"发送私聊历史给 {from_user}: {len(history)} 条消息")
                        except Exception as e:
                            print(f"获取私聊历史出错: {e}")
                            send_msg(conn, 'PRIVATE_HISTORY|error|获取历史记录失败')
                            
                elif cmd == 'CALL_ACCEPT':
                    # CALL_ACCEPT|from_user|to_user|udp_port
                    try:
                        if len(parts) < 4:
                            print(f"CALL_ACCEPT消息格式错误: {data}")
                            send_msg(conn, f'ERROR|通话请求格式错误')
                            continue

                        _, from_user, to_user, udp_port = parts
                        if DEBUG_CALL:
                            print(f"===== CALL ACCEPT DEBUG =====")
                            print(f"  从 {from_user} 接受 {to_user} 的通话")
                            print(f"  客户端IP: {addr[0]}, UDP端口: {udp_port}")

                        # 验证参数
                        try:
                            client_ip = addr[0]
                            client_udp_port = int(udp_port)
                            if client_udp_port <= 0 or client_udp_port > 65535:
                                raise ValueError(f"无效的UDP端口: {client_udp_port}")
                        except ValueError as e:
                            print(f"解析UDP端口错误: {e}")
                            send_msg(conn, f'ERROR|无效的UDP端口号')
                            continue
                            
                        print(f"接受语音通话: {from_user} -> {to_user}, UDP: {client_ip}:{client_udp_port}")

                        with lock:
                            # 验证双方都在线
                            if to_user not in clients:
                                print(f"发起方 {to_user} 不在线")
                                send_msg(conn, f'ERROR|发起方不在线，通话已取消')
                                continue
                                
                            # 保存接受者的UDP地址
                            udp_addresses[from_user] = (client_ip, client_udp_port)
                            print(f"更新接收者UDP地址: {from_user} -> {client_ip}:{client_udp_port}")
                            
                            # 确认发起者的UDP地址存在
                            if to_user not in udp_addresses:
                                print(f"错误: 发起者 {to_user} 的UDP地址不存在")
                                send_msg(conn, f'ERROR|无法获取发起方的网络地址')
                                continue
                                
                            # 验证发起者地址完整性
                            caller_ip, caller_port = udp_addresses[to_user]
                            if caller_ip is None or caller_port is None:
                                print(f"错误: 发起者 {to_user} 的UDP地址不完整: {udp_addresses[to_user]}")
                                send_msg(conn, f'ERROR|发起方的网络地址不完整')
                                continue
                                
                            print(f"确认发起者 {to_user} 的UDP地址: {udp_addresses[to_user]}")

                            # 记录通话状态
                            active_calls[from_user] = (to_user, (client_ip, client_udp_port))
                            active_calls[to_user] = (from_user, udp_addresses[to_user])

                            # 转发通话已接受消息给发起者
                            if to_user in clients:
                                try:
                                    # 向发起方发送接收方的UDP地址
                                    accept_msg = f'CALL_ACCEPTED|{from_user}|{client_ip}|{client_udp_port}'
                                    send_msg(clients[to_user], accept_msg)
                                    print(f"发送CALL_ACCEPTED给发起方 {to_user}: {accept_msg}")
                                        
                                    # 验证通话建立
                                    print(f"通话建立成功: {from_user} <-> {to_user}")
                                    print(f"  {from_user} 的UDP地址: {udp_addresses.get(from_user)}")
                                    print(f"  {to_user} 的UDP地址: {udp_addresses.get(to_user)}")
                                except Exception as e:
                                    print(f"发送CALL_ACCEPTED失败: {e}")
                                    send_msg(conn, f'ERROR|通知发起方失败: {e}')
                                    # 清理通话状态
                                    if from_user in active_calls:
                                        del active_calls[from_user]
                                    if to_user in active_calls:
                                        del active_calls[to_user]
                            else:
                                print(f"错误: {to_user} 不在线，无法发送CALL_ACCEPTED")
                                send_msg(conn, f'ERROR|发起方已下线，通话已取消')

                        if DEBUG_CALL:
                            print("===== CALL ACCEPT DEBUG END =====")
                    except Exception as e:
                        print(f"处理CALL_ACCEPT出错: {e}")
                        send_msg(conn, f'ERROR|处理通话接受失败')
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
    print(f'Server listening on {HOST}:{PORT} (TCP) and {HOST}:{UDP_PORT} (UDP)')

    # 启动UDP音频处理线程
    udp_thread = threading.Thread(target=handle_udp_audio, daemon=True)
    udp_thread.start()

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


if __name__ == '__main__':
    start_server() 