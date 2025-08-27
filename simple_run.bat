@echo off
chcp 65001 > nul
echo Запуск портала квитанций зарплаты...
echo.

REM Проверяем наличие Python
echo Проверка наличия Python...
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ОШИБКА] Python не найден. Пожалуйста, установите Python 3.8 или выше.
    pause
    exit /b 1
) else (
    echo Python найден успешно.
    echo.
)

REM Проверяем наличие файла credentials.json
if not exist "src\credentials.json" (
    echo [ПРЕДУПРЕЖДЕНИЕ] Файл src\credentials.json не найден!
    echo Для работы с Google Таблицами необходим файл учетных данных.
    echo.
)

REM Проверяем наличие файла .env
if not exist ".env" (
    echo [ПРЕДУПРЕЖДЕНИЕ] Файл .env не найден!
    echo Создаем файл .env с настройками по умолчанию...
    echo SPREADSHEET_ID=ваш_идентификатор_google_таблицы> .env
    echo SECRET_KEY=dev_key_change_in_production>> .env
    echo.
    echo [ВАЖНО] Пожалуйста, отредактируйте файл .env и укажите ID вашей Google таблицы.
    echo.
)

REM Активируем виртуальное окружение, если оно существует
if exist "venv\Scripts\activate.bat" (
    echo Активация виртуального окружения...
    call venv\Scripts\activate.bat
    echo.
)

REM Запускаем приложение напрямую
echo Приложение будет доступно по адресу: http://localhost:5000
echo Для остановки сервера нажмите Ctrl+C
echo.
python src\main.py

pause
