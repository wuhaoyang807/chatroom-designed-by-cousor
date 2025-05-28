@echo off
echo 开始打包聊天客户端...
echo.

echo 清理之前的构建文件...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo.
echo 开始使用PyInstaller打包...
pyinstaller ChatClient.spec

echo.
if exist "dist\ChatClient.exe" (
    echo 打包成功！
    echo 可执行文件位置: dist\ChatClient.exe
    echo.
    echo 用户数据将保存在: %USERPROFILE%\Documents\ChatClient\
    echo 包括:
    echo   - 聊天记录
    echo   - 语音消息
    echo   - 文件传输记录
    echo   - 日志文件
) else (
    echo 打包失败，请检查错误信息
)

echo.
pause 