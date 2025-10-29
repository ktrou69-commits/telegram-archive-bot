@echo off
echo Installing Archive Bot dependencies...
echo.

echo Installing python-telegram-bot with job-queue support...
pip install "python-telegram-bot[job-queue]==20.6"

echo Installing other dependencies...
pip install python-dotenv==1.0.0
pip install aiofiles==23.2.1
pip install requests==2.31.0
pip install urllib3==2.0.7
pip install "requests[socks]==2.31.0"

echo.
echo Dependencies installed successfully!
echo You can now run the bot with: python src/bot.py
pause
