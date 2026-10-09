from datetime import date, timedelta
import io
import os
import re
import sqlite3
import pandas as pd
import psycopg2
import streamlit as st

# --- Настройка страницы ---
st.set_page_config(
    page_title="Для моего Солнышка", page_icon="📚", layout="wide"
)

# --- CSS-стили для интерфейса ---
st.markdown(
    """
    <style>
    .block-container {
        max-width: 95% !important;
        padding-top: 3.5rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    div[data-testid="stDataFrame"] div[role="grid"] div[role="gridcell"] {
        text-align: center !important;
        justify-content: center !important;
    }
    div[data-testid="stTextInput"] label, 
    div[data-testid="stDateInput"] label, 
    div[data-testid="stSelectbox"] label {
        margin-bottom: 0.3rem !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

LOCAL_DB = "local_tutor.db"

# Словарь для перевода дней недели на русский
RUS_WEEKDAYS = {
    "Mon": "ПН",
    "Tue": "ВТ",
    "Wed": "СР",
    "Thu": "ЧТ",
    "Fri": "ПТ",
    "Sat": "СБ",
    "Sun": "ВС",
}


def format_date_with_weekday(d_str_or_date):
  if isinstance(d_str_or_date, str):
    dt = pd.to_datetime(d_str_or_date)
  else:
    dt = pd.to_datetime(d_str_or_date)
  day_num = dt.strftime("%d.%m")
  eng_weekday = dt.strftime("%a")
  rus_weekday = RUS_WEEKDAYS.get(eng_weekday, "")
  return f"{day_num} {rus_weekday}"


# --- Диалоговые окна ---
@st.dialog("⚠️ Ошибка: Дубликат ученика")
def duplicate_error_dialog(error_message):
  st.error(error_message)
  st.write(
      "Нельзя создать или изменить ученика так, чтобы его данные полностью"
      " совпадали с другим учеником."
  )
  if st.button("Понятно", type="primary", use_container_width=True):
    st.rerun()


@st.dialog("🗑️ Подтверждение удаления")
def delete_student_dialog(student_id, student_fullname):
  st.warning(f"Удалить ученика **{student_fullname}**?")
  col_y, col_n = st.columns(2)
  with col_y:
    if st.button("Да, удалить", type="primary", use_container_width=True):
      l_conn = get_local_connection()
      cursor = l_conn.cursor()
      cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
      cursor.execute(
          "DELETE FROM attendance WHERE student_id = ?", (student_id,)
      )
      l_conn.commit()
      l_conn.close()
      st.session_state["has_unsaved_changes"] = True
      st.success("Ученик удален!")
      st.rerun()
  with col_n:
    if st.button("Отмена", use_container_width=True):
      st.rerun()


# --- Подключения ---
def get_supabase_connection():
  db_url = os.getenv("DATABASE_URL")
  if not db_url:
    try:
      db_url = st.secrets["DATABASE_URL"]
    except Exception:
      st.error(
          "Не найден DATABASE_URL в секретах Streamlit или переменных"
          " окружения!"
      )
      st.stop()
  return psycopg2.connect(db_url)


def get_local_connection():
  conn = sqlite3.connect(LOCAL_DB)
  conn.row_factory = sqlite3.Row
  return conn


# Инициализация локальной базы SQLite (буфера)
def init_local_db():
  conn = get_local_connection()
  cursor = conn.cursor()
  cursor.execute(
      """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY,
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
            paid INTEGER DEFAULT 0,
            lesson_exists INTEGER DEFAULT 0,
            homework TEXT DEFAULT '',
            PRIMARY KEY (student_id, date)
        )
    """
  )
  conn.commit()
  conn.close()


init_local_db()


# Функция получения посещаемости из локальной БД
def get_local_attendance():
  l_conn = get_local_connection()
  cursor = l_conn.cursor()
  cursor.execute(
      "SELECT student_id, date, status, paid, lesson_exists, homework FROM attendance"
  )
  rows = cursor.fetchall()
  l_conn.close()
  return {(r["student_id"], r["date"]): dict(r) for r in rows}


# Синхронизация: Скачать данные из Supabase в локальный SQLite
def pull_from_cloud():
  try:
    s_conn = get_supabase_connection()
    s_cursor = s_conn.cursor()

    s_cursor.execute("SELECT id, name, surname, grade FROM students")
    cloud_students = s_cursor.fetchall()

    s_cursor.execute(
        "SELECT student_id, date, status, paid, lesson_exists, homework FROM attendance"
    )
    cloud_attendance = s_cursor.fetchall()

    s_cursor.close()
    s_conn.close()

    l_conn = get_local_connection()
    l_cursor = l_conn.cursor()
    l_cursor.execute("DELETE FROM attendance")
    l_cursor.execute("DELETE FROM students")

    for sid, name, surname, grade in cloud_students:
      l_cursor.execute(
          "INSERT INTO students (id, name, surname, grade) VALUES (?, ?, ?, ?)",
          (sid, name, surname, grade),
      )

    for sid, d_str, stat, paid, l_exists, hw in cloud_attendance:
      l_cursor.execute(
          """
            INSERT INTO attendance (student_id, date, status, paid, lesson_exists, homework)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
          (sid, d_str, stat, paid, l_exists, hw),
      )

    l_conn.commit()
    l_conn.close()
    return True
  except Exception as e:
    st.error(f"Ошибка загрузки из облака: {e}")
    return False


# --- Инициализация и очистка локального буфера при старте ---
if "db_initialized" not in st.session_state:
  init_local_db()

  l_conn = get_local_connection()
  cursor = l_conn.cursor()
  cursor.execute("DELETE FROM attendance")
  cursor.execute("DELETE FROM students")
  l_conn.commit()
  l_conn.close()

  pull_from_cloud()

  st.session_state["db_initialized"] = True
  st.session_state["has_unsaved_changes"] = False

# --- Боковая панель: Синхронизация ---
st.sidebar.header("☁️ Синхронизация с облаком")
has_changes = st.session_state.get("has_unsaved_changes", False)

if has_changes:
  st.sidebar.warning("⚠️ Есть несохраненные изменения!")
  import streamlit.components.v1 as components

  components.html(
      """
        <script>
            window.addEventListener('beforeunload', function (e) {
                e.preventDefault();
                e.returnValue = '';
            });
        </script>
    """,
      height=0,
  )
else:
  st.sidebar.success("✅ Все изменения синхронизированы")

if st.sidebar.button(
    "💾 Сохранить в облако", type="primary", use_container_width=True
):
  with st.spinner("Выгрузка данных в Supabase..."):
    try:
      l_conn = get_local_connection()
      l_cursor = l_conn.cursor()

      l_cursor.execute("SELECT id, name, surname, grade FROM students")
      local_students = l_cursor.fetchall()

      l_cursor.execute(
          "SELECT student_id, date, status, paid, lesson_exists, homework FROM attendance"
      )
      local_attendance = l_cursor.fetchall()
      l_conn.close()

      s_conn = get_supabase_connection()
      s_conn.autocommit = True
      s_cursor = s_conn.cursor()

      s_cursor.execute("DELETE FROM attendance")
      s_cursor.execute("DELETE FROM students")

      for row in local_students:
        s_cursor.execute(
            "INSERT INTO students (id, name, surname, grade) VALUES (%s, %s, %s, %s)",
            tuple(row),
        )

      for row in local_attendance:
        s_cursor.execute(
            """
                INSERT INTO attendance (student_id, date, status, paid, lesson_exists, homework)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
            tuple(row),
        )

      s_cursor.close()
      s_conn.close()

      st.session_state["has_unsaved_changes"] = False
      st.sidebar.success("Успешно сохранено в облако!")
      st.rerun()
    except Exception as e:
      st.sidebar.error(f"Ошибка сохранения: {e}")

if st.sidebar.button(
    "🔄 Скачать из облака (сбросить локальные)", use_container_width=True
):
  if pull_from_cloud():
    st.session_state["has_unsaved_changes"] = False
    st.success("Данные успешно обновлены из облака!")
    st.rerun()


def extract_grade_num(grade_str):
  if not grade_str or grade_str == "-":
    return ""
  match = re.search(r"\d+", grade_str)
  return match.group(0) if match else grade_str


def capitalize_name(text):
  if not text:
    return ""
  return " ".join([word.capitalize() for word in text.strip().split()])


def get_all_students_local():
  l_conn = get_local_connection()
  cursor = l_conn.cursor()
  cursor.execute("SELECT id, name, surname, grade FROM students")
  rows = cursor.fetchall()
  l_conn.close()
  return [dict(r) for r in rows]


all_students = get_all_students_local()

# --- Управление учениками ---
st.sidebar.divider()
st.sidebar.header("Управление учениками")

with st.sidebar.form("add_student_form", clear_on_submit=True):
  st.subheader("Добавить ученика")
  f_name = st.text_input("Имя *")
  f_surname = st.text_input("Фамилия *")
  f_grade = st.text_input("Класс * (например: 4б или '-')")

  if st.form_submit_button("Добавить"):
    if f_name.strip() and f_surname.strip() and f_grade.strip():
      clean_name = capitalize_name(f_name)
      clean_surname = capitalize_name(f_surname)
      clean_grade = f_grade.strip()

      l_conn = get_local_connection()
      cursor = l_conn.cursor()
      cursor.execute(
          "SELECT id FROM students WHERE name = ? AND surname = ? AND grade ="
          " ?",
          (clean_name, clean_surname, clean_grade),
      )
      exists = cursor.fetchone()

      if exists:
        l_conn.close()
        duplicate_error_dialog(
            f"Ученик {clean_surname} {clean_name} (класс {clean_grade})"
            " уже существует!"
        )
      else:
        cursor.execute(
            "INSERT INTO students (name, surname, grade) VALUES (?, ?, ?)",
            (clean_name, clean_surname, clean_grade),
        )
        l_conn.commit()
        l_conn.close()
        st.session_state["has_unsaved_changes"] = True
        st.sidebar.success("Ученик добавлен в локальный буфер!")
        st.rerun()
    else:
      st.sidebar.error("Заполните все поля!")


# --- Функция генерации Excel отчета из SQLite ---
def generate_excel_report(start_d, end_d, grade_filter, all_st, local_att):
  output = io.BytesIO()
  date_range = [
      (start_d + timedelta(days=days)).strftime("%Y-%m-%d")
      for days in range((end_d - start_d).days + 1)
  ]

  table_data = {}
  for s in all_st:
    g_num = extract_grade_num(s["grade"])

    if grade_filter != "Все классы":
      if grade_filter == "-" and s["grade"] != "-":
        continue
      elif (
          grade_filter != "-"
          and g_num != grade_filter
          and s["grade"] != grade_filter
      ):
        continue

    full_name = f"{s['surname']} {s['name']}" + (
        f" [{s['grade']}]" if s["grade"] and s["grade"] != "-" else ""
    )
    table_data[full_name] = {
        format_date_with_weekday(d): "" for d in date_range
    }

    for d_str in date_range:
      att = local_att.get((s["id"], d_str))
      if att and att["lesson_exists"] == 1:
        fmt_d = format_date_with_weekday(d_str)

        l_conn_rep = get_local_connection()
        cursor_rep = l_conn_rep.cursor()
        cursor_rep.execute(
            """
                SELECT homework FROM attendance 
                WHERE student_id = ? AND date < ? AND lesson_exists = 1 AND homework != ''
                ORDER BY date DESC LIMIT 1
            """,
            (s["id"], d_str),
        )
        r_hw = cursor_rep.fetchone()
        l_conn_rep.close()
        cur_hw = r_hw["homework"] if r_hw and r_hw["homework"] else "-"

        status_text = att["status"] or "Не указано"
        paid_text = "Оплачено" if att["paid"] == 1 else "Не оплачено"
        next_hw = att["homework"] or "-"

        cell_text = (
            f"Посещение: {status_text}\n"
            f"Оплата: {paid_text}\n"
            f"Текущее ДЗ: {cur_hw}\n"
            f"ДЗ на след: {next_hw}"
        )

        if fmt_d in table_data[full_name]:
          table_data[full_name][fmt_d] = cell_text

  df_excel = pd.DataFrame.from_dict(table_data, orient="index")
  if not df_excel.empty:
    df_excel = df_excel.sort_index()

  with pd.ExcelWriter(output, engine="openpyxl") as writer:
    header_info = pd.DataFrame([
        [
            "📅 Отчетный период:",
            f"{start_d.strftime('%d.%m.%Y')} — {end_d.strftime('%d.%m.%Y')}",
        ],
        ["🎓 Класс:", grade_filter],
        [],
    ])
    header_info.to_excel(
        writer,
        sheet_name="Журнал репетитора",
        index=False,
        header=False,
        startrow=0,
    )

    df_excel.to_excel(
        writer, sheet_name="Журнал репетитора", startrow=3, index=True
    )

  return output.getvalue()


# --- Основной экран (фильтры) ---
today_val = date.today()
monday_val = today_val - timedelta(days=today_val.weekday())
sunday_val = monday_val + timedelta(days=6)

has_no_grade = any(s["grade"] == "-" for s in all_students)
all_grade_nums = sorted(
    list(
        set(
            extract_grade_num(s["grade"])
            for s in all_students
            if s["grade"] and s["grade"] != "-"
        )
    )
)
filter_options = ["Все классы"] + all_grade_nums
if has_no_grade:
  filter_options.append("-")

f_col1, f_col2, f_col3 = st.columns(3)
with f_col1:
  start_date = st.date_input("📅Дата начала:", value=monday_val, key="start")
with f_col2:
  end_date = st.date_input("🚧Дата окончания:", value=sunday_val, key="end")
with f_col3:
  filter_grade = st.selectbox("🎓Класс", filter_options)

st.divider()

# --- Блок отчетов в боковой панели ---
st.sidebar.divider()
st.sidebar.header("📊 Отчеты Excel")
report_start = st.sidebar.date_input(
    "С такого периода", value=monday_val, key="rep_start"
)
report_end = st.sidebar.date_input(
    "По такой период", value=sunday_val, key="rep_end"
)

excel_bytes = generate_excel_report(
    report_start, report_end, filter_grade, all_students, get_local_attendance()
)

st.sidebar.download_button(
    label="📥 Скачать отчет Excel",
    data=excel_bytes,
    file_name=f"tutor_journal_{report_start}_{report_end}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    disabled=has_changes,
    use_container_width=True,
)
if has_changes:
  st.sidebar.caption(
      "⚠️ Доступно только при синхронизированных данных (нет"
      " несохраненных изменений)."
  )

st.sidebar.divider()
st.sidebar.markdown("""
### 📌 Легенда
- 🟢 — присутствовал
- 🟡 — отменил заранее
- 🔴 — несвоевременно
- 🔘 — не заполнено
- ✅ — оплачено 
- ❌ — не оплачено
- 📘 — ДЗ заполнено
- 📕 — ДЗ пусто
""")


def build_emoji_string(stat, paid, hw):
  p_emoji = (
      "🟢"
      if stat == "Present" or stat == "Присутствовал"
      else (
          "🟡"
          if stat == "Отменил заранее"
          else "🔴" if stat == "Несвоевременно отменил" else "🔘"
      )
  )
  pay_emoji = "✅" if paid == 1 else "❌"
  hw_emoji = "📘" if (hw and hw.strip()) else "📕"
  return f"{p_emoji} {pay_emoji} {hw_emoji}"


def get_current_homework_for_date(student_id, current_date_str):
  l_conn = get_local_connection()
  cursor = l_conn.cursor()
  cursor.execute(
      """
        SELECT homework FROM attendance 
        WHERE student_id = ? AND date < ? AND lesson_exists = 1 AND homework != ''
        ORDER BY date DESC LIMIT 1
    """,
      (student_id, current_date_str),
  )
  row = cursor.fetchone()
  l_conn.close()
  if row and row["homework"]:
    return row["homework"]
  return ""


local_attendance = get_local_attendance()

all_student_dict = {}
for s in all_students:
  g_str = f" ({s['grade']})" if s["grade"] and s["grade"] != "-" else ""
  all_sqlite_name = f"{s['surname']} {s['name']}{g_str}"
  all_student_dict[all_sqlite_name] = s["id"]

if all_student_dict and start_date <= end_date:
  date_range = [
      (start_date + timedelta(days=days)).strftime("%Y-%m-%d")
      for days in range((end_date - start_date).days + 1)
  ]

  table_data = {}
  for s in all_students:
    g_num = extract_grade_num(s["grade"])

    if filter_grade != "Все классы":
      if filter_grade == "-" and s["grade"] != "-":
        continue
      elif (
          filter_grade != "-"
          and g_num != filter_grade
          and s["grade"] != filter_grade
      ):
        continue

    full_name = f"{s['surname']} {s['name']}" + (
        f" [{s['grade']}]" if s["grade"] and s["grade"] != "-" else ""
    )
    table_data[full_name] = {
        format_date_with_weekday(d): "" for d in date_range
    }

    for d_str in date_range:
      att = local_attendance.get((s["id"], d_str))
      if att and att["lesson_exists"] == 1:
        fmt_d = format_date_with_weekday(d_str)
        if fmt_d in table_data[full_name]:
          table_data[full_name][fmt_d] = build_emoji_string(
              att["status"], att["paid"], att["homework"]
          )

  df = pd.DataFrame.from_dict(table_data, orient="index")
  if not df.empty:
    df = df.sort_index()
    st.dataframe(df, use_container_width=True)

    st.divider()
    st.subheader("📋 Карточка ученика и управление занятием")

    selected_student_row = st.selectbox(
        "Выберите ученика", ["-- Выберите ученика --"] + list(df.index)
    )

    if selected_student_row != "-- Выберите ученика --":
      selected_sid = None
      for s in all_students:
        fn = f"{s['surname']} {s['name']}" + (
            f" [{s['grade']}]" if s["grade"] and s["grade"] != "-" else ""
        )
        if fn == selected_student_row:
          selected_sid = s["id"]
          break

      if selected_sid:
        s_data = next(s for s in all_students if s["id"] == selected_sid)
        edit_mode_key = f"edit_mode_{selected_sid}"
        if edit_mode_key not in st.session_state:
          st.session_state[edit_mode_key] = False

        if not st.session_state[edit_mode_key]:
          grade_disp = (
              f"Класс: {s_data['grade']}"
              if s_data["grade"] and s_data["grade"] != "-"
              else "Без класса"
          )
          st.markdown(
              f"**Ученик:** {s_data['surname']} {s_data['name']} &nbsp;|&nbsp;"
              f" **{grade_disp}**"
          )

          lesson_date = st.date_input(
              "Дата урока", value=date.today(), key=f"card_date_{selected_sid}"
          )
          lesson_date_str = lesson_date.strftime("%Y-%m-%d")

          l_conn_single = get_local_connection()
          cursor_single = l_conn_single.cursor()
          cursor_single.execute(
              "SELECT student_id, date, status, paid, lesson_exists, homework FROM attendance WHERE student_id = ? AND date = ?",
              (selected_sid, lesson_date_str),
          )
          single_row = cursor_single.fetchone()
          l_conn_single.close()

          att_record = (
              dict(single_row)
              if single_row
              else {
                  "lesson_exists": 0,
                  "status": "",
                  "paid": 0,
                  "homework": "",
              }
          )

          current_hw_text = get_current_homework_for_date(
              selected_sid, lesson_date_str
          )

          w_key_les = f"les_exist_{selected_sid}_{lesson_date_str}"
          w_key_stat = f"status_sel_{selected_sid}_{lesson_date_str}"
          w_key_paid = f"paid_chk_{selected_sid}_{lesson_date_str}"
          w_key_hw = f"hw_txt_{selected_sid}_{lesson_date_str}"


          def save_to_sqlite():
            l_exists = 1 if st.session_state.get(w_key_les) else 0
            stat = st.session_state.get(w_key_stat, "")
            paid = 1 if st.session_state.get(w_key_paid) else 0
            hw = st.session_state.get(w_key_hw, "")

            l_conn = get_local_connection()
            cursor = l_conn.cursor()
            if l_exists == 0 and not stat and paid == 0 and not hw.strip():
              cursor.execute(
                  "DELETE FROM attendance WHERE student_id = ? AND date = ?",
                  (selected_sid, lesson_date_str),
              )
            else:
              cursor.execute(
                  """
                    INSERT INTO attendance (student_id, date, status, paid, lesson_exists, homework)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(student_id, date) DO UPDATE SET
                        status=excluded.status,
                        paid=excluded.paid,
                        lesson_exists=excluded.lesson_exists,
                        homework=excluded.homework
                """,
                  (selected_sid, lesson_date_str, stat, paid, l_exists, hw),
              )
            l_conn.commit()
            l_conn.close()
            st.session_state["has_unsaved_changes"] = True


          lesson_exists_toggle = st.checkbox(
              "Урок есть",
              value=bool(att_record["lesson_exists"]),
              key=w_key_les,
              on_change=save_to_sqlite,
          )

          if lesson_exists_toggle:
            st.markdown("---")
            st.text_area(
                "Текущее домашнее задание",
                value=current_hw_text,
                disabled=True,
                key=f"cur_hw_display_{selected_sid}_{lesson_date_str}",
            )

            status_options = [
                "",
                "Присутствовал",
                "Отменил заранее",
                "Несвоевременно отменил",
            ]
            cur_stat = att_record["status"]
            idx = (
                status_options.index(cur_stat)
                if cur_stat in status_options
                else 0
            )

            st.selectbox(
                "Посещаемость",
                status_options,
                index=idx,
                key=w_key_stat,
                on_change=save_to_sqlite,
            )
            st.checkbox(
                "Оплата получена",
                value=bool(att_record["paid"]),
                key=w_key_paid,
                on_change=save_to_sqlite,
            )
            st.text_area(
                "ДЗ на следующий урок",
                value=att_record["homework"],
                key=w_key_hw,
                on_change=save_to_sqlite,
            )

          st.divider()
          col1, _, col2 = st.columns([2, 3, 2])
          with col1:
            if st.button("✏️ Редактировать ученика", key=f"edit_{selected_sid}"):
              st.session_state[edit_mode_key] = True
              st.rerun()
          with col2:
            if st.button("🗑️ Удалить ученика", key=f"del_{selected_sid}"):
              delete_student_dialog(
                  selected_sid, f"{s_data['surname']} {s_data['name']}"
              )

        else:
          with st.form(f"edit_form_{selected_sid}"):
            new_name = st.text_input("Имя", value=s_data["name"])
            new_surname = st.text_input("Фамилия", value=s_data["surname"])
            new_grade = st.text_input("Класс", value=s_data["grade"])

            c1, c2 = st.columns(2)
            with c1:
              if st.form_submit_button("💾 Сохранить"):
                if (
                    new_name.strip()
                    and new_surname.strip()
                    and new_grade.strip()
                ):
                  clean_name = capitalize_name(new_name)
                  clean_surname = capitalize_name(new_surname)
                  clean_grade = new_grade.strip()

                  l_conn = get_local_connection()
                  cursor = l_conn.cursor()

                  cursor.execute(
                      "SELECT id FROM students WHERE name = ? AND surname = ?"
                      " AND grade = ? AND id != ?",
                      (clean_name, clean_surname, clean_grade, selected_sid),
                  )
                  conflict = cursor.fetchone()

                  if conflict:
                    l_conn.close()
                    duplicate_error_dialog(
                        f"Ученик {clean_surname} {clean_name} (класс"
                        f" {clean_grade}) уже существует в базе!"
                    )
                  else:
                    cursor.execute(
                        "UPDATE students SET name = ?, surname = ?, grade = ?"
                        " WHERE id = ?",
                        (
                            clean_name,
                            clean_surname,
                            clean_grade,
                            selected_sid,
                        ),
                    )
                    l_conn.commit()
                    l_conn.close()
                    st.session_state["has_unsaved_changes"] = True
                    st.session_state[edit_mode_key] = False
                    st.success("Обновлено!")
                    st.rerun()
            with c2:
              if st.form_submit_button("❌ Отмена"):
                st.session_state[edit_mode_key] = False
                st.rerun()