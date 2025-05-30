# 聊天软件

**更新时间：2025年05月16日20时**

------

## 一、程序运行
### 1. 启动服务端
在终端执行：

```bash
cd server
python main.py
```
### 2. 启动客户端1
在终端执行：
```bash
cd client
python main.py
```
### 3.启动客户端2
在终端执行：
```bash
cd client
python main1.py
```

------
## 二、目前实现的功能
本系统是基于python和PQt实现的简易聊天程序，目前具备下述功能
1. **用户注册**
2. **添加删除好友**：输入用户名称以添加好友，选中好友一键删除
3. **用户在线显示**：在线用户和离线用户使用颜色区分
4. **一对一私聊**：
5. **创建及加入聊天群组**：
6. **群组成员显示**
7. **聊天动态和静态表情包**
8. **群组内的实时聊天**
9. **群内的匿名聊天**
10. **群消息历史记录**
11. **私聊消息历史记录**
12. **调整画面分辨率**
13. **更换背景图片**
14. **增加了上传表情包功能**
15. **增加了用户注销功能**：注销后无法登录需要重新注册
16. **增加了发送语音功能**
17. **增加了语音变音功能**
18. **增加了文件上传和下载功能**
19. **封装python为可执行文件**
20. **日志记录模块**
------

## 三、技术实现
* TCP主要通信协议,端口12345，文本传输通过换行符作为消息边界
* TCP文件传输，端口12347
* UDP语音传输，动态端口


1. **使用TCP对数据进行传输**： 提供可靠的数据传输以及用户状态检查
2. **使用CSV文件储存数据**：简单容易实现，便于调试
3. **使用HASH储存密码**：比明文储存更加安全
4. **异常处理报错**：在网络通信过程中条件报错反馈，更容易调试
5. **分块文件传输**：将文件进行分块传输，使用专用端口，并添加错误重试
6. **好友关系处理**：添加删除好友对CSV中的好友关系进行操作
7. **在线显示功能**：服务端维护clients全局字典进行管理，客户端更新颜色和状态
8. **一对一私聊**：服务器对消息进行中转
9. **历史记录显示**：保存聊天记录到CSV，并在私聊界面对历史消息文件进行加载
10. **群聊**：群组信息和群成员关系分别储存，并创建ID进行搜索添加
11. **表情包**：首先对表情进行预加载，在聊天区域创建布局后添加表情
12. **历史消息**：用户之间的消息单独储存在文件夹，并按照用户名字典排序确保文件名统一
13. **分辨率调整**：预设多种分辨率，对主窗口进行调整并居中显示
14. **背景图片**：循环切换背景，使用CSS样式设置背景
15. **上传表情包**：允许选择本地表情，并复制到资源目录，之后对表情列表进行实时刷新
16. **语音发送**：使用PyAudio进行录制，通过Base64编码传输，对语音进行压缩，提高传输速度
17. **语音变音**：通过改变音频的采样频率实现变音，线性插值确保语音平滑
18. 

------
## 四、代码记录
1.**五月24日通过VPS调试**
2.第二次调试