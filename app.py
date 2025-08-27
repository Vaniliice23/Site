import os
import re
import time
import threading
from io import BytesIO

from flask import Flask, render_template, request, send_file
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv


# Load env from local .env next to this file if present
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)


app = Flask(__name__, template_folder='templates')
app.secret_key = os.getenv("SECRET_KEY", "dev_key_change_in_production")


# ====== Config ======
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Квитанции (Ив-2)")
SHEET_RANGE = os.getenv("SHEET_RANGE", "A:U")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Cache TTLs
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # matrix + index
EMPLOYEE_TTL_SECONDS = int(os.getenv("EMPLOYEE_TTL_SECONDS", "300"))


# ====== Globals (in-memory cache) ======
_sheets_service = None
_cache_lock = threading.Lock()
_payslip_matrix_cache = None  # list[list[str]] with merged cells resolved
_name_to_row_index_cache = {}  # normalized_name -> start_row_index
_cache_last_refresh = 0.0
_refresh_in_progress = False

# Per-employee result cache: normalized_name -> (timestamp, structured_payslip)
_employee_result_cache = {}


# ====== Google Sheets helpers ======
def get_google_sheets_service():
    """Create or return a singleton Google Sheets service."""
    global _sheets_service
    if _sheets_service is not None:
        return _sheets_service

    try:
        credentials_path = os.path.join(os.path.dirname(__file__), "credentials.json")
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Файл credentials.json не найден по пути: {credentials_path}")
        credentials = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        _sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return _sheets_service
    except Exception as e:
        print(f"Ошибка при создании сервиса Google Sheets: {e}")
        return None


def _fetch_values_and_merges():
    """Fetch raw sheet values and merges only (minimized fields)."""
    service = get_google_sheets_service()
    if not service:
        return [], []

    # 1) Values
    values = []
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!{SHEET_RANGE}"
        ).execute()
        values = result.get("values", [])
    except Exception as e:
        print(f"Ошибка получения значений из Google Sheets: {e}")

    # 2) Merges for the specific sheet only, with fields filter
    merges = []
    try:
        meta = service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID,
            fields="sheets(properties(title),merges)"
        ).execute()
        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == SHEET_NAME:
                merges = sheet.get("merges", []) or []
                break
    except Exception as e:
        print(f"Ошибка получения метаданных Google Sheets: {e}")

    return values, merges


def _rectify_grid(values):
    """Make rectangular grid from ragged values list by padding with empty strings."""
    if not values:
        return []
    max_cols = max(len(r) for r in values)
    grid = []
    for row in values:
        padded = list(row) + [""] * (max_cols - len(row))
        grid.append(padded)
    return grid


def _apply_merges(grid, merges):
    """Fill merged cell areas with the top-left value where grid cells are empty."""
    if not grid or not merges:
        return grid

    num_rows = len(grid)
    num_cols = len(grid[0]) if num_rows else 0

    for merge in merges:
        try:
            start_row = merge.get("startRowIndex", 0)
            end_row = merge.get("endRowIndex", 0)
            start_col = merge.get("startColumnIndex", 0)
            end_col = merge.get("endColumnIndex", 0)

            # Skip ranges outside of our loaded grid
            if start_row >= num_rows or start_col >= num_cols:
                continue

            top_left_value = grid[start_row][start_col] if start_row < num_rows and start_col < num_cols else ""
            for r in range(start_row, min(end_row, num_rows)):
                row = grid[r]
                for c in range(start_col, min(end_col, num_cols)):
                    if not row[c]:
                        row[c] = top_left_value
        except Exception:
            # Be resilient to unexpected merge shapes
            continue
    return grid


def _build_name_index(grid):
    """Create mapping: normalized_name -> first row index where the block starts."""
    index = {}
    for row_idx, row in enumerate(grid):
        left_name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        right_name = str(row[6]).strip() if len(row) > 6 and row[6] else ""
        left_norm = normalize_name(left_name)
        right_norm = normalize_name(right_name)

        if left_norm and left_norm not in index:
            index[left_norm] = row_idx
        if right_norm and right_norm not in index:
            index[right_norm] = row_idx
    return index


def _refresh_cache_sync():
    """Synchronously refresh the matrix and index caches."""
    global _payslip_matrix_cache, _name_to_row_index_cache, _cache_last_refresh
    values, merges = _fetch_values_and_merges()
    grid = _rectify_grid(values)
    grid = _apply_merges(grid, merges)
    index = _build_name_index(grid)
    with _cache_lock:
        _payslip_matrix_cache = grid
        _name_to_row_index_cache = index
        _cache_last_refresh = time.time()


def _background_refresh():
    global _refresh_in_progress
    try:
        _refresh_cache_sync()
    finally:
        with _cache_lock:
            _refresh_in_progress = False


def _ensure_cache_ready(block_if_empty=True):
    """Ensure cache exists; trigger background refresh if TTL expired."""
    global _refresh_in_progress
    with _cache_lock:
        have_cache = _payslip_matrix_cache is not None and _name_to_row_index_cache
        age = time.time() - _cache_last_refresh if have_cache else 1e9
        expired = age > CACHE_TTL_SECONDS
        if not have_cache and block_if_empty:
            # First load synchronously
            pass
        elif have_cache and expired and not _refresh_in_progress:
            _refresh_in_progress = True
            t = threading.Thread(target=_background_refresh, daemon=True)
            t.start()
            return

    # Do the synchronous load outside of the lock
    if _payslip_matrix_cache is None and block_if_empty:
        _refresh_cache_sync()


# ====== Domain logic (unchanged public helpers kept for compatibility) ======
def normalize_name(name):
    if not name:
        return ""
    normalized = re.sub(r"\s+", " ", str(name).strip().lower())
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return normalized


def format_number(value):
    """Форматирует число с пробелами для тысяч"""
    if not value or value == "0":
        return ""
    try:
        clean_value = re.sub(r"[^\d]", "", str(value))
        if clean_value:
            number = int(clean_value)
            return f"{number:,}".replace(",", " ")
    except Exception:
        pass
    return str(value)


def extract_month_year(cell_value):
    """Извлекает только месяц и год, убирая номер квитанции"""
    if not cell_value:
        return "", ""

    cell_str = str(cell_value).strip()

    month_year_match = re.search(r'(\d{1,2})\.(\d{4})', cell_str)
    if month_year_match:
        month = month_year_match.group(1)
        year = month_year_match.group(2)
        return month, year

    if '.' in cell_str and any(char.isalpha() for char in cell_str):
        parts = cell_str.split()
        if len(parts) >= 1:
            month_year_part = parts[0]
            if '.' in month_year_part:
                month_year_split = month_year_part.split('.')
                if len(month_year_split) >= 2:
                    return month_year_split[0], month_year_split[1]

    numbers = re.findall(r'\d+', cell_str)
    if len(numbers) >= 2:
        if len(numbers[1]) == 4 and numbers[1].startswith('20'):
            return numbers[0], numbers[1]

    return cell_str, ""


def extract_employee_payslip_data(payslip_data, employee_row_start, employee_name):
    try:
        employee_row = payslip_data[employee_row_start]
        left_name = str(employee_row[1]).strip() if len(employee_row) > 1 and employee_row[1] else ""
        right_name = str(employee_row[6]).strip() if len(employee_row) > 6 and employee_row[6] else ""
        normalized_search_name = normalize_name(employee_name)
        is_left_side = normalize_name(left_name) == normalized_search_name
        payslip_structure = {
            'employee_name': employee_name,
            'month': '',
            'year': '',
            'accrued': {
                'salary': '',
                'bonus': '',
                'personal_bonus': '',
                'other_accruals': '',
                'supplier_bonus': ''
            },
            'withheld': {
                'advance': '',
                'vacation': '',
                'sick_leave': '',
                'ndfl': '',
                'other_withholdings': '',
                'debt_withholding': '',
                'za_kartu': ''
            },
            'issue': '',
            'debt_balance': ''
        }
        col_offset = 0 if is_left_side else 5

        if len(employee_row) > col_offset + 3:
            month_cell = str(employee_row[col_offset + 3]).strip()
            month, year = extract_month_year(month_cell)
            payslip_structure['month'] = month
            if not year and len(employee_row) > col_offset + 4:
                year = str(employee_row[col_offset + 4]).strip()
            payslip_structure['year'] = year

        total_accrued = 0
        total_withheld = 0

        for i in range(8):
            row_idx = employee_row_start + i
            if row_idx >= len(payslip_data):
                break
            row = payslip_data[row_idx]

            label = str(row[col_offset + 1]).strip() if len(row) > col_offset + 1 else ""
            value = str(row[col_offset + 2]).strip() if len(row) > col_offset + 2 else ""

            if "Оклад" in label and value:
                payslip_structure['accrued']['salary'] = value
                try:
                    total_accrued += int(re.sub(r"[^\d]", "", value))
                except Exception:
                    pass
            elif "Премия" in label and value:
                payslip_structure['accrued']['bonus'] = value
                try:
                    total_accrued += int(re.sub(r"[^\d]", "", value))
                except Exception:
                    pass
            elif "Личный план" in label and value:
                payslip_structure['accrued']['personal_bonus'] = value
                try:
                    total_accrued += int(re.sub(r"[^\d]", "", value))
                except Exception:
                    pass
            elif "Прочие начисления" in label and value:
                payslip_structure['accrued']['other_accruals'] = value
                try:
                    total_accrued += int(re.sub(r"[^\d]", "", value))
                except Exception:
                    pass
            elif "Бонусы от постав" in label and value:
                payslip_structure['accrued']['supplier_bonus'] = value
                try:
                    total_accrued += int(re.sub(r"[^\d]", "", value))
                except Exception:
                    pass

            right_label = str(row[col_offset + 3]).strip() if len(row) > col_offset + 3 else ""
            right_value = str(row[col_offset + 4]).strip() if len(row) > col_offset + 4 else ""

            if "Аванс" in right_label and right_value:
                payslip_structure['withheld']['advance'] = right_value
                try:
                    total_withheld += int(re.sub(r"[^\d]", "", right_value))
                except Exception:
                    pass
            elif "Пропуск" in right_label and right_value:
                payslip_structure['withheld']['vacation'] = right_value
                try:
                    total_withheld += int(re.sub(r"[^\d]", "", right_value))
                except Exception:
                    pass
            elif "Обед" in right_label and right_value:
                payslip_structure['withheld']['sick_leave'] = right_value
                try:
                    total_withheld += int(re.sub(r"[^\d]", "", right_value))
                except Exception:
                    pass
            elif "НДФЛ" in right_label and right_value:
                payslip_structure['withheld']['ndfl'] = right_value
                try:
                    total_withheld += int(re.sub(r"[^\d]", "", right_value))
                except Exception:
                    pass
            elif "Прочие удержания" in right_label and right_value:
                payslip_structure['withheld']['other_withholdings'] = right_value
                try:
                    total_withheld += int(re.sub(r"[^\d]", "", right_value))
                except Exception:
                    pass
            elif "Удержание долга" in right_label and right_value:
                payslip_structure['withheld']['debt_withholding'] = right_value
                try:
                    total_withheld += int(re.sub(r"[^\d]", "", right_value))
                except Exception:
                    pass
            elif "Зп на карту" in right_label and right_value:
                payslip_structure['withheld']['za_kartu'] = right_value
            elif "Остаток долга" in right_label and right_value:
                payslip_structure['debt_balance'] = right_value
            elif "ВЫДАНО" in label and value:
                payslip_structure['issue'] = format_number(value)

        payslip_structure['total_withheld'] = format_number(str(total_withheld)) if total_withheld > 0 else ""

        if not payslip_structure['issue'] and total_accrued > 0:
            issued_amount = total_accrued - total_withheld
            payslip_structure['issue'] = format_number(str(issued_amount))

        return payslip_structure
    except Exception as e:
        print(f"Ошибка при извлечении данных квитанции: {e}")
        return None


def search_employee_payslip(employee_name):
    """Fast lookup using cached matrix + index; API calls happen only in refresh."""
    try:
        if not employee_name:
            return None, "Пустое имя сотрудника"

        normalized_name = normalize_name(employee_name)

        # 1) Try employee-level cache first
        cached = _employee_result_cache.get(normalized_name)
        if cached:
            ts, data = cached
            if time.time() - ts <= EMPLOYEE_TTL_SECONDS:
                return data, None

        # 2) Ensure shared caches are ready
        _ensure_cache_ready(block_if_empty=True)

        with _cache_lock:
            grid = _payslip_matrix_cache
            index = _name_to_row_index_cache

        if not grid or not index:
            return None, "Не удалось получить данные квитанций"

        employee_row_start = index.get(normalized_name)
        if employee_row_start is None:
            return None, f"Сотрудник '{employee_name}' не найден в квитанциях"

        structured_payslip = extract_employee_payslip_data(grid, employee_row_start, employee_name)

        # Store in employee cache
        _employee_result_cache[normalized_name] = (time.time(), structured_payslip)
        return structured_payslip, None
    except Exception as e:
        error_msg = f"Ошибка при поиске квитанции: {str(e)}"
        print(error_msg)
        return None, error_msg


def create_payslip_image(payslip_data, employee_name):
    try:
        width = 600
        height = 400
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        font_path = os.path.join(os.path.dirname(__file__), "Montserrat-Regular.ttf")
        try:
            font = ImageFont.truetype(font_path, 12)
            font_title = ImageFont.truetype(font_path, 16)
            font_small = ImageFont.truetype(font_path, 10)
        except Exception:
            font = ImageFont.load_default()
            font_title = ImageFont.load_default()
            font_small = ImageFont.load_default()

        def draw_table_cell(x, y, w, h, text, font_obj, text_color="black", bg_color=None):
            if bg_color:
                draw.rectangle([x, y, x + w, y + h], fill=bg_color, outline="black")
            else:
                draw.rectangle([x, y, x + w, y + h], outline="black")
            bbox = draw.textbbox((0, 0), text, font=font_obj)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            text_x = x + (w - text_w) // 2
            text_y = y + (h - text_h) // 2
            draw.text((text_x, text_y), text, font=font_obj, fill=text_color)

        draw_table_cell(50, 20, 400, 30, f"{employee_name}", font_title, text_color="black", bg_color="white")
        month_year = f"{payslip_data.get('month', '')}.{payslip_data.get('year', '')}" if payslip_data.get('month') and payslip_data.get('year') else ""
        draw_table_cell(450, 20, 100, 30, month_year, font_title, text_color="black", bg_color="white")

        y = 60
        draw_table_cell(50, y, 200, 25, "Начислено:", font, bg_color="lightgreen")
        total_accrued = format_number(payslip_data['accrued'].get('salary', '0'))
        draw_table_cell(250, y, 100, 25, total_accrued, font)
        draw_table_cell(350, y, 100, 25, "Удержано:", font, bg_color="lightcoral")
        total_withheld_display = payslip_data.get('total_withheld', '0')
        draw_table_cell(450, y, 100, 25, total_withheld_display, font)

        y += 25
        accrued_items = [
            ("Оклад", format_number(payslip_data['accrued'].get('salary', '0'))),
            ("Премия", format_number(payslip_data['accrued'].get('bonus', ''))),
            ("Личный план", format_number(payslip_data['accrued'].get('personal_bonus', ''))),
            ("Прочие начисления", format_number(payslip_data['accrued'].get('other_accruals', '')))
        ]
        withheld_items = [
            ("Аванс", format_number(payslip_data['withheld'].get('advance', ''))),
            ("Пропуск", format_number(payslip_data['withheld'].get('vacation', ''))),
            ("Обед", format_number(payslip_data['withheld'].get('sick_leave', ''))),
            ("НДФЛ", format_number(payslip_data['withheld'].get('ndfl', '')))
        ]

        max_rows = max(len(accrued_items), len(withheld_items))
        for i in range(max_rows):
            if i < len(accrued_items):
                acc_name, acc_value = accrued_items[i]
                draw_table_cell(50, y, 200, 25, acc_name, font_small)
                draw_table_cell(250, y, 100, 25, str(acc_value) if acc_value else "", font_small)
            else:
                draw_table_cell(50, y, 200, 25, "", font_small)
                draw_table_cell(250, y, 100, 25, "", font_small)
            if i < len(withheld_items):
                with_name, with_value = withheld_items[i]
                draw_table_cell(350, y, 100, 25, with_name, font_small)
                draw_table_cell(450, y, 100, 25, str(with_value) if with_value else "", font_small)
            else:
                draw_table_cell(350, y, 100, 25, "", font_small)
                draw_table_cell(450, y, 100, 25, "", font_small)
            y += 25

        y += 10
        draw_table_cell(50, y, 200, 25, "Бонусы от постав-ов", font_small)
        draw_table_cell(250, y, 100, 25, format_number(payslip_data['accrued'].get('supplier_bonus', '')), font_small)
        draw_table_cell(350, y, 100, 25, "Прочие удержания", font_small)
        draw_table_cell(450, y, 100, 25, format_number(payslip_data['withheld'].get('other_withholdings', '')), font_small)

        y += 25
        y += 10
        draw_table_cell(50, y, 200, 30, "ВЫДАНО", font, bg_color="yellow")
        draw_table_cell(250, y, 100, 30, str(payslip_data.get('issue', '0')), font, bg_color="yellow")
        draw_table_cell(350, y, 100, 30, "Остаток долга", font, bg_color="lightblue")
        draw_table_cell(450, y, 100, 30, format_number(payslip_data.get('debt_balance', '0')), font, bg_color="lightblue")

        return img
    except Exception as e:
        print(f"Ошибка при создании изображения: {e}")
        return None


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        employee_name = request.form.get("employee_name", "").strip()
        if not employee_name:
            return render_template("index.html",
                                   title="Поиск квитанций зарплаты",
                                   error="Пожалуйста, введите имя и фамилию")
        payslip_data, error = search_employee_payslip(employee_name)
        if error:
            return render_template("index.html",
                                   title="Поиск квитанций зарплаты",
                                   employee_name=employee_name,
                                   error=error)
        if payslip_data:
            return render_template("index.html",
                                   title="Поиск квитанций зарплаты",
                                   employee_name=employee_name,
                                   payslip_found=True,
                                   payslip_data=payslip_data)
    return render_template("index.html", title="Поиск квитанций зарплаты")


@app.route("/download_image", methods=["POST"])
def download_image():
    employee_name = request.form.get("employee_name", "").strip()
    if not employee_name:
        return "Имя сотрудника не указано", 400
    payslip_data, error = search_employee_payslip(employee_name)
    if error:
        return error, 500
    if payslip_data:
        image = create_payslip_image(payslip_data, employee_name)
        if image:
            img_io = BytesIO()
            image.save(img_io, "PNG")
            img_io.seek(0)
            return send_file(img_io, mimetype="image/png", as_attachment=True, download_name=f"payslip_{employee_name}.png")
        else:
            return "Ошибка при создании изображения квитанции", 500
    else:
        return "Квитанция не найдена для создания изображения", 404


def _startup_preload():
    """Optionally warm up cache on startup for instant first query."""
    preload = os.getenv("PRELOAD_ON_STARTUP", "1")
    if preload == "1":
        try:
            _ensure_cache_ready(block_if_empty=True)
        except Exception as e:
            print(f"Предзагрузка кэша завершилась с ошибкой: {e}")


_startup_preload()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")

