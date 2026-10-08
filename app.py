from datetime import date, timedelta
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
        padding-top: 2rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    div[data-testid="stDataFrame"] div[role="grid"] div[role="gridcell"] {
        text-align: center !important;
        justify-content: center !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

LOCAL_DB = "local_tutor.db"


# --- Подключения ---
def get_supabase_connection():
  db_url = os.getenv("DATABASE_URL")
  if not db_url:
    try:
      db_url = st.secrets["DATABASE_URL"]
    except Exception:
      db_url = "postgresql://postgres.doqhdknjzfrtekrwoqnk:VWRKnSLy4N5rXVHp@aws-1-eu-west-3.pooler.supabase.com:6543/postgres"
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


if "db_initialized" not in st.session_state:
  l_conn = get_local_connection()
  cursor = l_conn.cursor()
  cursor.execute("SELECT COUNT(*) FROM students")
  count = cursor.fetchone()[0]
  l_conn.close()

  if count == 0:
    pull_from_cloud()

  st.session_state["db_initialized"] = True
  st.session_state["has_unsaved_changes"] = False

st.title("📚 Журнал English Dream (SQLite Buffer Mode)")

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
      l_conn = get_local_connection()
      cursor = l_conn.cursor()
      cursor.execute(
          "INSERT INTO students (name, surname, grade) VALUES (?, ?, ?)",
          (f_name.strip(), f_surname.strip(), f_grade.strip()),
      )
      l_conn.commit()
      l_conn.close()
      st.session_state["has_unsaved_changes"] = True
      st.sidebar.success("Ученик добавлен в локальный буфер!")
      st.rerun()
    else:
      st.sidebar.error("Заполните все поля!")

# --- Легенда ---
st.sidebar.divider()
st.sidebar.markdown("""
### 📌 Легенда
* 🟢 — присутствовал | 🟡 — отменил заранее | 🔴 — несвоевременно | 🔘 — не заполнено
* 💰 — оплачено | ⛔ — не оплачено
* 📘 — ДЗ заполнено | 📕 — ДЗ пусто
""")

# --- Основной экран ---
st.header("Электронный журнал")

today = date.today()
monday = today - timedelta(days=today.weekday())
sunday = monday + timedelta(days=6)

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
  start_date = st.date_input("С какого числа", value=monday, key="start")
with f_col2:
  end_date = st.date_input("По какое число", value=sunday, key="end")
with f_col3:
  filter_grade = st.selectbox("Фильтр по классу", filter_options)

st.divider()


def build_emoji_string(stat, paid, hw):
  p_emoji = (
      "🟢"
      if stat == "Присутствовал"
      else (
          "🟡"
          if stat == "Отменил заранее"
          else "🔴" if stat == "Несвоевременно отменил" else "🔘"
      )
  )
  pay_emoji = "💰" if paid == 1 else "⛔"
  hw_emoji = "📘" if (hw and hw.strip()) else "📕"
  return f"{p_emoji} {pay_emoji} {hw_emoji}"


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


def get_local_attendance():
  l_conn = get_local_connection()
  cursor = l_conn.cursor()
  cursor.execute(
      "SELECT student_id, date, status, paid, lesson_exists, homework FROM attendance"
  )
  rows = cursor.fetchall()
  l_conn.close()
  return {(r["student_id"], r["date"]): dict(r) for r in rows}


# Функция для автоматического поиска ДЗ с предыдущего урока
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
        pd.to_datetime(d).strftime("%d.%m"): "" for d in date_range
    }

    for d_str in date_range:
      att = local_attendance.get((s["id"], d_str))
      if att and att["lesson_exists"] == 1:
        fmt_d = pd.to_datetime(d_str).strftime("%d.%m")
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

          # Точечный запрос из базы для конкретной даты
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

          # Автоматически получаем текущее ДЗ с предыдущего урока
          current_hw_text = get_current_homework_for_date(
              selected_sid, lesson_date_str
          )

          # Уникальные ключи виджетов с привязкой к дате
          w_key_les = f"les_exist_{selected_sid}_{lesson_date_str}"
          w_key_stat = f"status_sel_{selected_sid}_{lesson_date_str}"
          w_key_paid = f"paid_chk_{selected_sid}_{lesson_date_str}"
          w_key_hw = f"hw_txt_{selected_sid}_{lesson_date_str}"  # ДЗ на следующий урок


          def save_to_sqlite():
            l_exists = 1 if st.session_state.get(w_key_les) else 0
            stat = st.session_state.get(w_key_stat, "")
            paid = 1 if st.session_state.get(w_key_paid) else 0
            hw = st.session_state.get(w_key_hw, "")  # Сохраняем ДЗ на будущее

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

            # 1. Текущее домашнее задание (только для чтения)
            st.text_area(
                "Текущее домашнее задание (с прошлого урока)",
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

            # 2. ДЗ на следующий урок (редактируемое)
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
                  l_conn = get_local_connection()
                  cursor = l_conn.cursor()
                  cursor.execute(
                      "UPDATE students SET name = ?, surname = ?, grade = ? WHERE id = ?",
                      (
                          new_name.strip(),
                          new_surname.strip(),
                          new_grade.strip(),
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