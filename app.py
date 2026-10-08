from datetime import date, timedelta
import re
import sqlite3
import pandas as pd
import streamlit as st

# --- Настройка страницы ---
st.set_page_config(
    page_title="Журнал репетитора", page_icon="📚", layout="wide"
)

# --- Усиленные CSS-стили для центрирования эмодзи в ячейках ---
st.markdown(
    """
    <style>
    .block-container {
        max-width: 95% !important;
        padding-top: 2rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    
    /* Принудительное центрирование во всех ячейках таблицы data_editor */
    div[data-testid="stDataEditor"] div[role="grid"] div[role="gridcell"] {
        text-align: center !important;
        justify-content: center !important;
    }
    
    /* Центрирование текста/эмодзи внутри выпадающих списков и ячеек с данными */
    div[data-testid="stDataEditor"] [data-baseweb="select"] span {
        text-align: center !important;
        width: 100% !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
    }
    
    div[data-testid="stDataEditor"] div[role="gridcell"] div {
        text-align: center !important;
        justify-content: center !important;
        align-items: center !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# --- Инициализация базы данных ---
conn = sqlite3.connect("tutor.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        surname TEXT,
        grade TEXT
    )
"""
)

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS attendance (
        student_id INTEGER,
        date TEXT,
        status TEXT,
        PRIMARY KEY (student_id, date),
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
"""
)
conn.commit()

st.title("📚 Журнал посещаемости репетитора")


# Функция для извлечения только цифры из класса (например, из "4б" -> "4")
def extract_grade_num(grade_str):
  if not grade_str:
    return ""
  match = re.search(r"\d+", grade_str)
  return match.group(0) if match else grade_str


# Загружаем всех учеников из базы
cursor.execute("SELECT id, name, surname, grade FROM students")
all_students = cursor.fetchall()

# --- Боковая панель: Управление учениками и легенда ---
st.sidebar.header("Управление учениками")

with st.sidebar.form("add_student_form", clear_on_submit=True):
  st.subheader("Добавить ученика")
  f_name = st.text_input("Имя")
  f_surname = st.text_input("Фамилия")
  f_grade = st.text_input("Класс (например: 4б или 7в)")

  submitted = st.form_submit_button("Добавить")
  if submitted:
    if f_name.strip() and f_surname.strip():
      cursor.execute(
          "INSERT INTO students (name, surname, grade) VALUES (?, ?, ?)",
          (f_name.strip(), f_surname.strip(), f_grade.strip()),
      )
      conn.commit()
      st.sidebar.success(f"Ученик {f_name} {f_surname} добавлен!")
      st.rerun()
    else:
      st.sidebar.error("Заполните хотя бы Имя и Фамилию.")

# Блок удаления учеников
all_student_dict = {}
for sid, name, surname, grade in all_students:
  grade_str = f" ({grade})" if grade else ""
  display_name = f"{surname} {name}{grade_str}"
  all_student_dict[display_name] = sid

if all_student_dict:
  st.sidebar.divider()
  st.sidebar.subheader("Удаление ученика")
  student_to_delete = st.sidebar.selectbox(
      "Выберите ученика", list(all_student_dict.keys())
  )
  if st.sidebar.button("Удалить ученика"):
    sid = all_student_dict[student_to_delete]
    cursor.execute("DELETE FROM students WHERE id = ?", (sid,))
    cursor.execute("DELETE FROM attendance WHERE student_id = ?", (sid,))
    conn.commit()
    st.sidebar.success(f"Ученик удален.")
    st.rerun()

# --- Легенда в боковой панели ---
st.sidebar.divider()
st.sidebar.markdown("""
### 📌 Подсказка (Легенда)
* 🟢 — Присутствовал
* 🟡 — Отменил заранее
* 🔴 — Несвоевременно отменил
""")

# --- Экран: Фильтры (период дат: текущая неделя ПН-ВС) ---
st.header("Электронный журнал")

# Расчет понедельника и воскресенья текущей недели
today = date.today()
monday_of_current_week = today - timedelta(days=today.weekday())
sunday_of_current_week = monday_of_current_week + timedelta(days=6)

all_grade_nums = sorted(
    list(set(extract_grade_num(g) for _, _, _, g in all_students if g))
)

f_col1, f_col2, f_col3 = st.columns(3)
with f_col1:
  start_date = st.date_input(
      "С какого числа", value=monday_of_current_week, key="start"
  )
with f_col2:
  end_date = st.date_input(
      "По какое число", value=sunday_of_current_week, key="end"
  )
with f_col3:
  filter_grade = st.selectbox(
      "Фильтр по классу (цифра)", ["Все классы"] + all_grade_nums
  )

st.divider()


# Вспомогательные функции конвертации
def status_to_emoji(stat):
  if stat == "Присутствовал":
    return "🟢"
  elif stat == "Отменил заранее":
    return "🟡"
  elif stat == "Несвоевременно отменил":
    return "🔴"
  return ""


def emoji_to_status(emoji):
  if emoji == "🟢":
    return "Присутствовал"
  elif emoji == "🟡":
    return "Отменил заранее"
  elif emoji == "🔴":
    return "Несвоевременно отменил"
  return None


# --- Основной экран: Интерактивная таблица посещаемости с автосохранением ---
if all_student_dict and start_date <= end_date:
  date_range = [
      (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
      for i in range((end_date - start_date).days + 1)
  ]

  cursor.execute(
      """
        SELECT s.id, s.name, s.surname, s.grade, a.date, a.status 
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id AND a.date BETWEEN ? AND ?
    """,
      (start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")),
  )
  records = cursor.fetchall()

  table_data = {}
  for sid, name, surname, grade, d_str, stat in records:
    g_num = extract_grade_num(grade)
    if filter_grade != "Все классы" and g_num != filter_grade:
      continue

    full_name = f"{surname} {name}" + (f" [{grade}]" if grade else "")
    if full_name not in table_data:
      table_data[full_name] = {
          pd.to_datetime(d).strftime("%d.%m"): {"db_date": d, "emoji": ""}
          for d in date_range
      }

    if d_str:
      formatted_d = pd.to_datetime(d_str).strftime("%d.%m")
      if full_name in table_data and formatted_d in table_data[full_name]:
        table_data[full_name][formatted_d]["emoji"] = status_to_emoji(stat)

  for sid, name, surname, grade in all_students:
    g_num = extract_grade_num(grade)
    if filter_grade != "Все классы" and g_num != filter_grade:
      continue
    full_name = f"{surname} {name}" + (f" [{grade}]" if grade else "")
    if full_name not in table_data:
      table_data[full_name] = {
          pd.to_datetime(d).strftime("%d.%m"): {"db_date": d, "emoji": ""}
          for d in date_range
      }

  flat_table_data = {}
  for fn, dates_dict in table_data.items():
    flat_table_data[fn] = {
        col_name: info["emoji"] for col_name, info in dates_dict.items()
    }

  df = pd.DataFrame.from_dict(flat_table_data, orient="index")
  if not df.empty:
    df = df.sort_index()

    column_config = {
        col: st.column_config.SelectboxColumn(
            col,
            options=["", "🟢", "🟡", "🔴"],
            required=False,
        )
        for col in df.columns
    }

    st.markdown(
        "💡 *Изменения в ячейках сохраняются автоматически сразу после"
        " выбора.*"
    )


    # Функция автосохранения при изменении ячейки
    def save_changes():
      edited_data = st.session_state["grid_editor"]
      current_indices = list(df.index)

      for row_idx_str, changes in edited_data["edited_rows"].items():
        row_idx = int(row_idx_str)
        full_name = current_indices[row_idx]

        target_sid = None
        for sid, name, surname, grade in all_students:
          fn = f"{surname} {name}" + (f" [{grade}]" if grade else "")
          if fn == full_name:
            target_sid = sid
            break

        if target_sid:
          for col_name, selected_emoji in changes.items():
            real_date = None
            if (
                full_name in table_data
                and col_name in table_data[full_name]
            ):
              real_date = table_data[full_name][col_name]["db_date"]

            if real_date:
              real_status = emoji_to_status(selected_emoji)

              if real_status:
                cursor.execute(
                    """
                                        INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?)
                                        ON CONFLICT(student_id, date) DO UPDATE SET status=excluded.status
                                    """,
                    (target_sid, real_date, real_status),
                )
              else:
                cursor.execute(
                    "DELETE FROM attendance WHERE student_id = ? AND date = ?",
                    (target_sid, real_date),
                )
      conn.commit()


    st.data_editor(
        df,
        column_config=column_config,
        use_container_width=True,
        key="grid_editor",
        on_change=save_changes,
    )

  else:
    st.info("Нет учеников для отображения (проверьте фильтр класса).")
elif start_date > end_date:
  st.error("Дата начала не может быть позже даты окончания!")

# --- Экспорт таблицы в Excel с выбором периода ---
st.sidebar.divider()
st.sidebar.subheader("Экспорт данных в Excel")

export_start = st.sidebar.date_input(
    "С какого числа (экспорт)", value=monday_of_current_week, key="exp_start"
)
export_end = st.sidebar.date_input(
    "По какое число (экспорт)", value=sunday_of_current_week, key="exp_end"
)

if st.sidebar.button("📥 Скачать Excel отчёт"):
  if export_start > export_end:
    st.sidebar.error("Дата начала не может быть позже даты окончания!")
  else:
    # Загружаем данные из БД строго за выбранный для экспорта период
    exp_date_range = [
        (export_start + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range((export_end - export_start).days + 1)
    ]

    cursor.execute(
        """
            SELECT s.id, s.name, s.surname, s.grade, a.date, a.status 
            FROM students s
            LEFT JOIN attendance a ON s.id = a.student_id AND a.date BETWEEN ? AND ?
        """,
        (
            export_start.strftime("%Y-%m-%d"),
            export_end.strftime("%Y-%m-%d"),
        ),
    )
    exp_records = cursor.fetchall()

    exp_table_data = {}
    for sid, name, surname, grade, d_str, stat in exp_records:
      full_name = f"{surname} {name}" + (f" [{grade}]" if grade else "")
      if full_name not in exp_table_data:
        exp_table_data[full_name] = {
            pd.to_datetime(d).strftime("%d.%m"): "" for d in exp_date_range
        }

      if d_str:
        formatted_d = pd.to_datetime(d_str).strftime("%d.%m")
        if (
            full_name in exp_table_data
            and formatted_d in exp_table_data[full_name]
        ):
          exp_table_data[full_name][formatted_d] = (
              status_to_emoji(stat) if stat else ""
          )

    # Добавляем всех учеников на случай, если у них не было отметок за этот период
    for sid, name, surname, grade in all_students:
      full_name = f"{surname} {name}" + (f" [{grade}]" if grade else "")
      if full_name not in exp_table_data:
        exp_table_data[full_name] = {
            pd.to_datetime(d).strftime("%d.%m"): "" for d in exp_date_range
        }

    exp_flat_data = {}
    for fn, dates_dict in exp_table_data.items():
      exp_flat_data[fn] = dates_dict

    exp_df = pd.DataFrame.from_dict(exp_flat_data, orient="index")
    if not exp_df.empty:
      exp_df = exp_df.sort_index()

      # Конвертируем эмодзи в слова для Excel
      emoji_to_full_text = {
          "🟢": "Присутствовал",
          "🟡": "Отменил заранее",
          "🔴": "Несвоевременно отменил",
          "": "",
      }

      for col in exp_df.columns:
        exp_df[col] = exp_df[col].map(emoji_to_full_text).fillna("")

      exp_df = exp_df.reset_index()
      exp_df.rename(columns={"index": "Ученик"}, inplace=True)

      import io

      output = io.BytesIO()
      with pd.ExcelWriter(output, engine="openpyxl") as writer:
        exp_df.to_excel(writer, index=False, sheet_name="Посещаемость")

      excel_data = output.getvalue()

      st.sidebar.download_button(
          label="💾 Сохранить файл",
          data=excel_data,
          file_name=f"tutor_report_{export_start.strftime('%d.%m.%Y')}-{export_end.strftime('%d.%m.%Y')}.xlsx",
          mime=(
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          ),
      )
    else:
      st.sidebar.warning("Нет данных за выбранный период.")