import socket
import threading
import csv
import hashlib
import os
import time
import shutil
import threading

# 服务器配置
HOST = '0.0.0.0'
PORT = 12345
UDP_PORT = 12346  # 为语音通话添加UDP端口
USER_CSV = 'users.csv'
FRIENDSHIP_CSV = 'friendships.csv'
GROUP_CSV = 'groups.csv'
GROUP_MEMBERS_CSV = 'group_members.csv'
DEBUG_CALL = True  # 添加调试标志
USER_FILES_DIR = 'user_files'
os.makedirs(USER_FILES_DIR, exist_ok=True)

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
                if (row['user_a'] == user_a and row['user_b'] == user_b) or (row['user_a'] == user_b and row['user_b'] == user_a):
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
                if (row['user_a'] == user_a and row['user_b'] == user_b) or (row['user_a'] == user_b and row['user_b'] == user_a):
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
                continue
                
            header_len = data[0]  # 第一个字节表示头部长度
            if len(data) < header_len + 1:
                continue
                
            header = data[1:header_len+1].decode('utf-8')
            # 头部格式：发送者|接收者
            try:
                sender, receiver = header.split('|')
                
                # 检查接收者是否在线和是否处于通话中
                with lock:
                    if receiver in active_calls and active_calls[receiver][0] == sender and receiver in udp_addresses:
                        # 转发音频数据到接收者
                        udp_socket.sendto(data, udp_addresses[receiver])
            except Exception as e:
                print(f"处理UDP音频数据出错: {e}")
        except Exception as e:
            print(f"UDP音频处理异常: {e}")

def send_msg(conn, msg):
    if not msg.endswith('\n'):
        msg += '\n'
    conn.send(msg.encode('utf-8'))

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
                        
                        # 保存发起者的UDP地址
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
                                        # 将通话请求转发给对方
                                        try:
                                            if DEBUG_CALL:
                                                print(f"  发送CALL_INCOMING到 {to_user}")
                                                print(f"  clients[{to_user}] 是否有效: {clients[to_user] is not None}")
                                            
                                            # 使用多次发送和确认，增加可靠性
                                            for i in range(3):  # 发送3次确保收到
                                                # 发送通话请求消息
                                                send_msg(to_user_conn, f'CALL_INCOMING|{from_user}')
                                                
                                                if DEBUG_CALL:
                                                    print(f"  第{i+1}次发送CALL_INCOMING，长度: {len(f'CALL_INCOMING|{from_user}')}，实际发送: {len(f'CALL_INCOMING|{from_user}')}字节")
                                                
                                                # 短暂延迟确保接收方有时间处理
                                                time.sleep(0.5)
                                            
                                            # 发送确认到发起方
                                            send_msg(conn, f'CALL_RESPONSE|SENDING|{to_user}')
                                            
                                            # 通知发起方对方已经收到通话请求
                                            if DEBUG_CALL:
                                                print(f"  CALL_INCOMING已多次发送，对方应该收到请求")
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
                        # 保存接受者的UDP地址
                        udp_addresses[from_user] = (client_ip, client_udp_port)
                        
                        # 记录通话状态
                        active_calls[from_user] = (to_user, (client_ip, client_udp_port))
                        active_calls[to_user] = (from_user, udp_addresses.get(to_user, (None, None)))
                        
                        # 转发通话已接受消息给发起者
                        if to_user in clients:
                            try:
                                to_user_udp_info = f"{client_ip}|{client_udp_port}"
                                
                                # 多次发送确保可靠性
                                for i in range(3):
                                    send_msg(clients[to_user], f'CALL_ACCEPTED|{from_user}|{to_user_udp_info}')
                                    if DEBUG_CALL:
                                        print(f"  第{i+1}次发送CALL_ACCEPTED给 {to_user}，长度: {len(f'CALL_ACCEPTED|{from_user}|{to_user_udp_info}')}，实际发送: {len(f'CALL_ACCEPTED|{from_user}|{to_user_udp_info}')}字节")
                                    time.sleep(0.5)
                            except Exception as e:
                                if DEBUG_CALL:
                                    print(f"  发送CALL_ACCEPTED失败: {e}")
                                del clients[to_user]  # 清理无效连接
                        elif DEBUG_CALL:
                            print(f"  错误: {to_user} 不在线，无法发送CALL_ACCEPTED")
                    
                    if DEBUG_CALL:
                        print("===== CALL ACCEPT DEBUG END =====")
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
                elif cmd == 'FILE_UPLOAD':
                    # FILE_UPLOAD|from_user|to_user|filename|filesize
                    _, from_user, to_user, fname, fsize = parts
                    fsize = int(fsize)
                    users = sorted([from_user, to_user])
                    dir_path = os.path.join(USER_FILES_DIR, f'{users[0]}__{users[1]}')
                    os.makedirs(dir_path, exist_ok=True)
                    file_path = os.path.join(dir_path, fname)
                    
                    # 接收文件数据
                    filedata = b''
                    while len(filedata) < fsize:
                        chunk = conn.recv(min(4096, fsize - len(filedata)))
                        if not chunk:
                            break
                        filedata += chunk
                    
                    # 保存文件
                    with open(file_path, 'wb') as f:
                        f.write(filedata)
                    print(f"文件已保存: {file_path}")
                    
                    # 主动推送文件列表给双方
                    file_list = os.listdir(dir_path)
                    with lock:
                        # 给自己推送
                        if from_user in clients:
                            send_msg(clients[from_user], 'FILE_LIST|' + '|'.join(file_list))
                        # 给对方推送
                        if to_user in clients:
                            send_msg(clients[to_user], 'FILE_LIST|' + '|'.join(file_list))
                elif cmd == 'FILE_LIST':
                    # FILE_LIST|from_user|to_user
                    _, from_user, to_user = parts
                    users = sorted([from_user, to_user])
                    dir_path = os.path.join(USER_FILES_DIR, f'{users[0]}__{users[1]}')
                    if os.path.exists(dir_path):
                        files = os.listdir(dir_path)
                    else:
                        files = []
                    send_msg(conn, 'FILE_LIST|' + '|'.join(files))
                elif cmd == 'FILE_DOWNLOAD':
                    # FILE_DOWNLOAD|from_user|to_user|filename
                    _, from_user, to_user, fname = parts
                    
                    def send_file_thread(conn, from_user, to_user, fname):
                        users = sorted([from_user, to_user])
                        dir_path = os.path.join(USER_FILES_DIR, f'{users[0]}__{users[1]}')
                        file_path = os.path.join(dir_path, fname)
                        print(f"[线程] 处理文件下载请求: {from_user} -> {to_user}, 文件: {fname}")
                        print(f"[线程] 文件路径: {file_path}")
                        try:
                            if os.path.exists(file_path):
                                filesize = os.path.getsize(file_path)
                                print(f"[线程] 文件大小: {filesize} 字节")
                                # 发送文件信息（确保以换行符结束）
                                try:
                                    response = f'FILE_DATA|{fname}|{filesize}\n'
                                    conn.send(response.encode('utf-8'))
                                    # 等待客户端确认开始传输
                                    try:
                                        conn.settimeout(5)
                                        ack = conn.recv(4)
                                        if not ack or ack != b'ACK\n':
                                            print(f"[线程] 警告: 客户端发送了标准ACK以外的确认: {ack}")
                                    except socket.timeout:
                                        print("[线程] 等待客户端确认超时，继续尝试发送文件")
                                    finally:
                                        conn.settimeout(None)
                                except Exception as e:
                                    print(f"[线程] 准备发送文件阶段出错: {e}")
                                    send_msg(conn, f'ERROR|准备发送文件失败: {e}')
                                    return
                                # 分块发送文件数据
                                with open(file_path, 'rb') as f:
                                    total_sent = 0
                                    chunk_size = 65536  # 64KB
                                    last_update_time = time.time()
                                    last_print_time = time.time()
                                    ack_interval = 524288  # 每512KB等待一次ACK
                                    last_ack_size = 0
                                    while total_sent < filesize:
                                        try:
                                            # 是否需要等待ACK
                                            if total_sent - last_ack_size >= ack_interval:
                                                try:
                                                    conn.settimeout(10)
                                                    print(f"[线程] 等待客户端ACK，已发送: {total_sent}/{filesize} 字节 ({total_sent/filesize*100:.1f}%)")
                                                    ack = conn.recv(4)
                                                    if not ack or ack != b'ACK\n':
                                                        print(f"[线程] 警告: 接收到无效的ACK信号: {ack}，尝试继续")
                                                    last_ack_size = total_sent
                                                    print("[线程] 收到ACK，继续发送")
                                                except socket.timeout:
                                                    print("[线程] 等待ACK超时，但继续传输")
                                                    last_ack_size = total_sent
                                                finally:
                                                    conn.settimeout(None)
                                            # 读取数据块
                                            chunk = f.read(chunk_size)
                                            if not chunk:
                                                break
                                            bytes_sent = conn.send(chunk)
                                            if bytes_sent == 0:
                                                print("[线程] 警告: 发送字节为0，可能连接有问题")
                                                time.sleep(0.1)
                                                continue
                                            total_sent += bytes_sent
                                            # 每秒打印一次传输进度
                                            current_time = time.time()
                                            if current_time - last_print_time >= 1.0:
                                                speed = (total_sent - last_update_time) / (current_time - last_update_time) / 1024 if current_time > last_update_time else 0
                                                print(f"[线程] 文件发送进度: {total_sent}/{filesize} 字节 ({total_sent/filesize*100:.1f}%), 速度: {speed:.1f} KB/s")
                                                last_print_time = current_time
                                                last_update_time = current_time
                                        except Exception as e:
                                            print(f"[线程] 发送文件数据时出错: {e}")
                                            try:
                                                conn.settimeout(3)
                                                send_msg(conn, f'ERROR|文件传输错误: {str(e)}')
                                            except:
                                                pass
                                            finally:
                                                conn.settimeout(None)
                                            return
                                    print(f"[线程] 文件 {fname} 发送完成")
                            else:
                                print(f"[线程] 文件不存在: {file_path}")
                                send_msg(conn, f'ERROR|文件不存在: {fname}')
                        except Exception as e:
                            print(f"[线程] 处理文件下载请求出错: {e}")
                            try:
                                send_msg(conn, f'ERROR|文件下载失败: {str(e)}')
                            except:
                                pass
                    
                    # 启动文件传输线程
                    t = threading.Thread(target=send_file_thread, args=(conn, from_user, to_user, fname), daemon=True)
                    t.start()
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
            conn, addr = s.accept()
            print(f'Connected by {addr}')
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

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

if __name__ == '__main__':
    start_server() 