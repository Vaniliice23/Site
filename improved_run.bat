@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo Портал квитанций зарплаты - Улучшенный скрипт запуска
echo ===================================================
echo.

REM Определяем текущую директорию
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
echo Директория скрипта: %SCRIPT_DIR%
echo.

REM Проверяем наличие Python
echo Проверка наличия Python...
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ОШИБКА] Python не найден. Пожалуйста, установите Python 3.8 или выше.
    echo Вы можете скачать Python с сайта: https://www.python.org/downloads/
    pause
    exit /b 1
) else (
    python --version
    echo Python найден успешно.
    echo.
)

REM Проверяем структуру проекта
echo Проверка структуры проекта...
if not exist "%SCRIPT_DIR%\src" (
    echo [ОШИБКА] Папка src не найдена в директории %SCRIPT_DIR%
    echo Пожалуйста, убедитесь, что вы запускаете скрипт из корневой папки проекта.
    pause
    exit /b 1
)

if not exist "%SCRIPT_DIR%\src\main.py" (
    echo [ОШИБКА] Файл src\main.py не найден.
    echo Пожалуйста, убедитесь, что структура проекта не нарушена.
    pause
    exit /b 1
)

if not exist "%SCRIPT_DIR%\requirements.txt" (
    echo [ОШИБКА] Файл requirements.txt не найден.
    echo Пожалуйста, убедитесь, что структура проекта не нарушена.
    pause
    exit /b 1
)

echo Структура проекта проверена успешно.
echo.

REM Проверяем наличие файла credentials.json
echo Проверка файла учетных данных Google...
if not exist "%SCRIPT_DIR%\src\credentials.json" (
    echo [ПРЕДУПРЕЖДЕНИЕ] Файл src\credentials.json не найден!
    echo.
    echo Для работы с Google Таблицами необходимо создать файл учетных данных.
    echo Инструкции по созданию файла credentials.json:
    echo 1. Перейдите в Google Cloud Console: https://console.cloud.google.com/
    echo 2. Создайте проект и включите Google Sheets API
    echo 3. Создайте сервисный аккаунт и скачайте ключ в формате JSON
    echo 4. Переименуйте скачанный файл в credentials.json
    echo 5. Поместите файл в папку src
    echo.
    echo Хотите продолжить без файла credentials.json? (y/n)
    set /p continue=
    if /i "!continue!" NEQ "y" (
        echo Установка прервана пользователем.
        pause
        exit /b 1
    )
    echo.
)

REM Проверяем наличие файла .env
echo Проверка файла конфигурации...
if not exist "%SCRIPT_DIR%\.env" (
    echo [ПРЕДУПРЕЖДЕНИЕ] Файл .env не найден!
    echo Создаем файл .env с настройками по умолчанию...
    echo SPREADSHEET_ID=ваш_идентификатор_google_таблицы> "%SCRIPT_DIR%\.env"
    echo SECRET_KEY=dev_key_change_in_production>> "%SCRIPT_DIR%\.env"
    echo.
    echo [ВАЖНО] Файл .env создан, но требует настройки!
    echo Пожалуйста, отредактируйте файл .env и укажите ID вашей Google таблицы.
    echo ID таблицы можно найти в URL: https://docs.google.com/spreadsheets/d/ЭТОТ_ID_НУЖНО_СКОПИРОВАТЬ/edit
    echo.
    echo Хотите открыть файл .env для редактирования? (y/n)
    set /p edit_env=
    if /i "!edit_env!" EQU "y" (
        start notepad "%SCRIPT_DIR%\.env"
        echo Пожалуйста, сохраните файл .env после редактирования и закройте Блокнот.
        echo Нажмите любую клавишу, чтобы продолжить после редактирования...
        pause >nul
    )
    echo.
)

REM Проверяем наличие виртуального окружения
echo Проверка виртуального окружения...
if not exist "%SCRIPT_DIR%\venv" (
    echo Виртуальное окружение не найдено. Создаем новое...
    python -m venv "%SCRIPT_DIR%\venv"
    if %ERRORLEVEL% NEQ 0 (
        echo [ОШИБКА] Не удалось создать виртуальное окружение.
        echo Пожалуйста, убедитесь, что у вас установлен модуль venv.
        pause
        exit /b 1
    )
    echo Виртуальное окружение создано успешно.
) else (
    echo Виртуальное окружение найдено.
)
echo.

REM Активируем виртуальное окружение
echo Активация виртуального окружения...
call "%SCRIPT_DIR%\venv\Scripts\activate.bat"
if %ERRORLEVEL% NEQ 0 (
    echo [ОШИБКА] Не удалось активировать виртуальное окружение.
    pause
    exit /b 1
)
echo Виртуальное окружение активировано успешно.
echo.

REM Устанавливаем зависимости
echo Установка зависимостей...
pip install -r "%SCRIPT_DIR%\requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo [ОШИБКА] Не удалось установить зависимости.
    echo Пожалуйста, проверьте подключение к интернету и права доступа.
    pause
    exit /b 1
)
echo Зависимости установлены успешно.
echo.

REM Запускаем приложение
echo Запуск портала квитанций зарплаты...
echo.
echo ===================================================
echo Приложение будет доступно по адресу: http://localhost:5000
echo Для остановки сервера нажмите Ctrl+C
echo ===================================================
echo.
python "%SCRIPT_DIR%\src\main.py"
if %ERRORLEVEL% NEQ 0 (
    echo [ОШИБКА] Не удалось запустить приложение.
    echo Пожалуйста, проверьте логи выше для получения дополнительной информации.
    pause
    exit /b 1
)

pause
