#!/bin/bash

# Скрипт для запуска портала квитанций зарплаты

# Проверяем наличие Python
if ! command -v python3 &> /dev/null; then
    echo "Python не найден. Пожалуйста, установите Python 3.8 или выше."
    exit 1
fi

# Проверяем наличие виртуального окружения
if [ ! -d "venv" ]; then
    echo "Создаем виртуальное окружение..."
    python3 -m venv venv
fi

# Активируем виртуальное окружение
source venv/bin/activate

# Устанавливаем зависимости
echo "Устанавливаем зависимости..."
pip install -r requirements.txt

# Проверяем наличие файла credentials.json
if [ ! -f "src/credentials.json" ]; then
    echo "ВНИМАНИЕ: Файл src/credentials.json не найден!"
    echo "Пожалуйста, поместите файл учетных данных Google в директорию src/"
    echo "Подробнее в README.md"
fi

# Проверяем наличие .env файла
if [ ! -f ".env" ]; then
    echo "Создаем файл .env с настройками по умолчанию..."
    echo "SPREADSHEET_ID=ваш_идентификатор_google_таблицы" > .env
    echo "SECRET_KEY=dev_key_change_in_production" >> .env
    echo "ВНИМАНИЕ: Отредактируйте файл .env, указав ID вашей Google таблицы!"
fi

# Запускаем приложение
echo "Запускаем портал квитанций зарплаты..."
echo "Приложение будет доступно по адресу: http://localhost:5000"
python src/main.py
