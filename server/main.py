import socket
import threading
import csv
import hashlib
import os

# 服务器配置
HOST = '0.0.0.0'
PORT = 12345
USER_CSV = 'users.csv'
FRIENDSHIP_CSV = 'friendships.csv'
GROUP_CSV = 'groups.csv'
GROUP_MEMBERS_CSV = 'group_members.csv'

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
lock = threading.Lock()

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
                        clients[f].send(f'FRIEND_ONLINE|{username}'.encode('utf-8'))
                    else:
                        clients[f].send(f'FRIEND_OFFLINE|{username}'.encode('utf-8'))
                except Exception:
                    pass

def handle_client(conn, addr):
    username = None
    try:
        while True:
            data = conn.recv(4096).decode('utf-8')
            if not data:
                break
            parts = data.split('|', 2)
            cmd = parts[0]
            if cmd == 'REGISTER':
                _, u, p = parts
                success, msg = register_user(u, p)
                conn.send(f'REGISTER_RESULT|{"OK" if success else "FAIL"}|{msg}'.encode('utf-8'))
            elif cmd == 'LOGIN':
                _, u, p = parts
                if authenticate_user(u, p):
                    with lock:
                        clients[u] = conn
                    username = u
                    conn.send('LOGIN_RESULT|OK|Login successful.'.encode('utf-8'))
                    notify_friends_status(username, True)
                else:
                    conn.send('LOGIN_RESULT|FAIL|Invalid username or password.'.encode('utf-8'))
            elif cmd == 'ADD_FRIEND':
                _, u, f = parts
                success, msg = add_friend(u, f)
                conn.send(f'ADD_FRIEND_RESULT|{"OK" if success else "FAIL"}|{msg}'.encode('utf-8'))
            elif cmd == 'DEL_FRIEND':
                _, u, f = parts
                success, msg = del_friend(u, f)
                conn.send(f'DEL_FRIEND_RESULT|{"OK" if success else "FAIL"}|{msg}'.encode('utf-8'))
            elif cmd == 'GET_FRIENDS':
                _, u = parts[:2]
                friends_status = get_friends_with_status(u)
                # 格式 FRIEND_LIST|user1:online|user2:offline|...
                friend_strs = [f"{f}:{'online' if online else 'offline'}" for f, online in friends_status]
                conn.send(f"FRIEND_LIST|{'|'.join(friend_strs)}".encode('utf-8'))
            elif cmd == 'MSG':
                # MSG|to_user|message
                _, to_user, msg = parts
                # 只允许发给好友
                if to_user not in get_friends(username):
                    conn.send(f'ERROR|You are not friends with {to_user}.'.encode('utf-8'))
                else:
                    with lock:
                        if to_user in clients:
                            clients[to_user].send(f'MSG|{username}|{msg}'.encode('utf-8'))
                        else:
                            conn.send(f'ERROR|User {to_user} not online.'.encode('utf-8'))
            elif cmd == 'EMOJI':
                # EMOJI|to_user|emoji_id
                _, to_user, emoji_id = parts
                if to_user not in get_friends(username):
                    conn.send(f'ERROR|You are not friends with {to_user}.'.encode('utf-8'))
                else:
                    with lock:
                        if to_user in clients:
                            clients[to_user].send(f'EMOJI|{username}|{emoji_id}'.encode('utf-8'))
                        else:
                            conn.send(f'ERROR|User {to_user} not online.'.encode('utf-8'))
            elif cmd == 'LOGOUT':
                break
            elif cmd == 'CREATE_GROUP':
                _, u, group_name = parts
                success, msg, group_id = create_group(group_name)
                if success:
                    join_group(group_id, u)
                conn.send(f'CREATE_GROUP_RESULT|{"OK" if success else "FAIL"}|{msg}|{group_id}'.encode('utf-8'))
            elif cmd == 'JOIN_GROUP':
                _, u, group_id = parts
                success, msg = join_group(group_id, u)
                conn.send(f'JOIN_GROUP_RESULT|{"OK" if success else "FAIL"}|{msg}|{group_id}'.encode('utf-8'))
            elif cmd == 'GET_GROUPS':
                _, u = parts[:2]
                groups = get_user_groups(u)
                # 格式 GROUP_LIST|group_id:group_name|...
                group_strs = [f'{gid}:{gname}' for gid, gname in groups]
                conn.send(f'GROUP_LIST|{"|".join(group_strs)}'.encode('utf-8'))
            elif cmd == 'GET_GROUP_MEMBERS':
                _, group_id = parts[:2]
                members = get_group_members(group_id)
                conn.send(f'GROUP_MEMBERS|{"|".join(members)}'.encode('utf-8'))
            elif cmd == 'GROUP_MSG':
                # GROUP_MSG|group_id|from_user|msg
                _, group_id, from_user, msg = parts
                members = get_group_members(group_id)
                print(f'群聊广播: group_id={group_id}, members={members}')
                save_group_message(group_id, from_user, msg)
                with lock:
                    for m in members:
                        if m in clients:
                            try:
                                clients[m].send(f'GROUP_MSG|{group_id}|{from_user}|{msg}'.encode('utf-8'))
                            except Exception as e:
                                print(f'发送给{m}失败: {e}')
            elif cmd == 'GROUP_MSG_ANON':
                # GROUP_MSG_ANON|group_id|anon_nick|msg
                _, group_id, anon_nick, msg = parts
                members = get_group_members(group_id)
                print(f'匿名群聊广播: group_id={group_id}, members={members}')
                save_group_message(group_id, None, msg, anon_nick=anon_nick)
                with lock:
                    for m in members:
                        if m in clients:
                            try:
                                clients[m].send(f'GROUP_MSG_ANON|{group_id}|{anon_nick}|{msg}'.encode('utf-8'))
                            except Exception as e:
                                print(f'发送给{m}失败: {e}')
            elif cmd == 'GET_GROUP_HISTORY':
                _, group_id = parts[:2]
                history = get_group_history(group_id)
                # 格式 GROUP_HISTORY|type|sender|msg|...
                resp = ['GROUP_HISTORY']
                for row in history:
                    resp.extend(row)
                conn.send('|'.join(resp).encode('utf-8'))
            else:
                conn.send('ERROR|Unknown command.'.encode('utf-8'))
    except Exception as e:
        print(f'Error: {e}')
    finally:
        if username:
            with lock:
                if username in clients:
                    del clients[username]
            notify_friends_status(username, False)
        conn.close()
        print(f'Connection from {addr} closed.')

def start_server():
    print(f'Server listening on {HOST}:{PORT}')
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
    members = []
    with open(GROUP_MEMBERS_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['group_id'] == group_id:
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

if __name__ == '__main__':
    start_server() 