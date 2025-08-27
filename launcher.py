import os
import sys
import subprocess

# Получаем текущую директорию скрипта
current_dir = os.path.dirname(os.path.abspath(__file__))

# Путь к main.py
main_path = os.path.join(current_dir, "src", "main.py")

# Путь к активации виртуального окружения
venv_python = os.path.join(current_dir, "venv", "Scripts", "python.exe")

print(f"Запуск приложения из: {current_dir}")
print(f"Путь к main.py: {main_path}")

# Проверяем существование файла main.py
if not os.path.exists(main_path):
    print(f"ОШИБКА: Файл {main_path} не найден!")
    input("Нажмите Enter для выхода...")
    sys.exit(1)

print("Файл main.py найден. Запускаем приложение...")

# Определяем, какой интерпретатор Python использовать
python_executable = sys.executable
if os.path.exists(venv_python):
    python_executable = venv_python
    print(f"Используется Python из виртуального окружения: {venv_python}")
else:
    print("Виртуальное окружение не найдено или не активно. Используется системный Python.")

# Запускаем приложение
try:
    subprocess.run([python_executable, main_path], check=True)
except Exception as e:
    print(f"ОШИБКА при запуске: {e}")
    input("Нажмите Enter для выхода...")
