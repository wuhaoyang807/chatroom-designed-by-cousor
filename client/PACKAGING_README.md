# 聊天客户端打包说明

## 修改内容

为了解决PyInstaller打包后资源文件和用户数据丢失的问题，我对代码进行了以下修改：

### 1. 添加了路径处理函数

- `resource_path()`: 处理静态资源文件路径（表情包、背景图片）
- `get_user_data_path()`: 处理用户数据路径（聊天记录、语音消息、文件等）

### 2. 路径分离策略

**静态资源（打包到exe中）：**
- `resources/` - 表情包文件
- `backgrounds/` - 背景图片

**用户数据（保存到用户目录）：**
- 聊天记录
- 语音消息
- 文件传输
- 日志文件

### 3. 用户数据存储位置

打包后的程序会将用户数据保存到：
- **Windows**: `%USERPROFILE%\Documents\ChatClient\`
- **Linux/Mac**: `~/.chatclient/`

目录结构：
```
ChatClient/
├── logs/           # 日志文件
├── voice_messages/ # 语音消息
└── files/          # 文件传输
```

## 打包步骤

### 方法1：使用批处理脚本（推荐）
```bash
cd client
build.bat
```

### 方法2：手动打包
```bash
cd client
pyinstaller ChatClient.spec
```

## 打包后的优势

1. **数据持久化**: 聊天记录和语音消息不会因为程序更新而丢失
2. **多用户支持**: 不同Windows用户有独立的数据目录
3. **便于备份**: 用户数据集中在一个目录，便于备份
4. **权限友好**: 不需要管理员权限即可运行

## 注意事项

1. 首次运行时会自动创建用户数据目录
2. 如果需要迁移旧数据，请手动复制到新的用户数据目录
3. 表情包和背景图片已打包到exe中，无需额外文件
4. 确保目标机器有足够的磁盘空间存储用户数据

## 测试建议

1. 在不同的Windows机器上测试
2. 测试聊天记录的保存和加载
3. 测试语音消息功能
4. 测试表情包显示
5. 测试背景切换功能 