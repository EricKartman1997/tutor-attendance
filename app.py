from datetime import date, timedelta
import os
import re
import pandas as pd
import psycopg2
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
    
    div[data-testid="stDataFrame"] div[role="grid"] div[role="gridcell"] {
        text-align: center !important;
        justify-content: center !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)


# --- Подключение к облачной базе данных Supabase (PostgreSQL) ---
def get_db_connection():
  try:
    db_url = st.secrets["DATABASE_URL"]
  except Exception:
    # Запасной вариант для локального запуска через Connection Pooler
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres.doqhdknjzfrtekrwoqnk:VWRKnSLy4N5rXVHp@aws-1-eu-west-3.pooler.supabase.com:5432/postgres",
    )
  return psycopg2.connect(db_url)


# Инициализация таблиц в облаке при первом запуске
def init_db():
  try:
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            name TEXT,
            surname TEXT,
            grade TEXT
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
            date TEXT,
            status TEXT,
            paid INTEGER DEFAULT 0,
            lesson_exists INTEGER DEFAULT 0,
            homework TEXT DEFAULT '',
            PRIMARY KEY (student_id, date)
        )
    """
    )
    cursor.close()
    conn.close()
  except Exception as e:
    st.error(f"Ошибка подключения к облачной базе: {e}")


init_db()

# --- Инициализация локального буфера в st.session_state ---
if "buffer_loaded" not in st.session_state:
  try:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, surname, grade FROM students")
    st.session_state["buf_students"] = cursor.fetchall()

    cursor.execute(
        "SELECT student_id, date, status, paid, lesson_exists, homework FROM attendance"
    )
    att_rows = cursor.fetchall()

    st.session_state["buf_attendance"] = {}
    for sid, d_str, stat, paid, l_exists, hw in att_rows:
      st.session_state["buf_attendance"][(sid, d_str)] = {
          "status": stat,
          "paid": paid,
          "lesson_exists": l_exists,
          "homework": hw,
      }

    cursor.close()
    conn.close()
    st.session_state["buffer_loaded"] = True
    st.session_state["has_unsaved_changes"] = False
  except Exception as e:
    st.error(f"Не удалось загрузить данные из облака: {e}")
    st.session_state["buf_students"] = []
    st.session_state["buf_attendance"] = {}

st.title("📚 Журнал репетитора (Буферный режим)")

# --- Кнопка синхронизации с облаком ---
st.sidebar.header("☁️ Синхронизация с облаком")
has_changes = st.session_state.get("has_unsaved_changes", False)

if has_changes:
  st.sidebar.warning("⚠️ Есть несохраненные изменения в буфере!")

  # JavaScript-код для предупреждения при закрытии вкладки
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
  with st.spinner("Загрузка данных в Supabase..."):
    try:
      conn = get_db_connection()
      conn.autocommit = True
      cursor = conn.cursor()

      cursor.execute("DELETE FROM attendance")
      cursor.execute("DELETE FROM students")

      for sid, name, surname, grade in st.session_state["buf_students"]:
        cursor.execute(
            "INSERT INTO students (id, name, surname, grade) VALUES (%s, %s, %s,"
            " %s)",
            (sid, name, surname, grade),
        )

      for (sid, d_str), data in st.session_state["buf_attendance"].items():
        cursor.execute(
            """
                INSERT INTO attendance (student_id, date, status, paid, lesson_exists, homework) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                sid,
                d_str,
                data["status"],
                data["paid"],
                data["lesson_exists"],
                data["homework"],
            ),
        )

      cursor.close()
      conn.close()
      st.session_state["has_unsaved_changes"] = False
      st.sidebar.success("Успешно сохранено в облако!")
      st.rerun()
    except Exception as e:
      st.sidebar.error(f"Ошибка сохранения: {e}")

if st.sidebar.button("🔄 Вернуться к облачным данным", use_container_width=True):
  for k in [
      "buffer_loaded",
      "has_unsaved_changes",
      "buf_students",
      "buf_attendance",
  ]:
    if k in st.session_state:
      del st.session_state[k]
  st.rerun()


def extract_grade_num(grade_str):
  if not grade_str or grade_str == "-":
    return ""
  match = re.search(r"\d+", grade_str)
  return match.group(0) if match else grade_str


all_students = st.session_state["buf_students"]

# --- Боковая панель: Управление учениками (в буфере) ---
st.sidebar.divider()
st.sidebar.header("Управление учениками")

with st.sidebar.form("add_student_form", clear_on_submit=True):
  st.subheader("Добавить ученика")
  f_name = st.text_input("Имя *")
  f_surname = st.text_input("Фамилия *")
  f_grade = st.text_input("Класс * (например: 4б или '-' если без класса)")

  submitted = st.form_submit_button("Добавить")
  if submitted:
    if f_name.strip() and f_surname.strip() and f_grade.strip():
      max_id = (
          max([s[0] for s in st.session_state["buf_students"]])
          if st.session_state["buf_students"]
          else 0
      )
      new_id = max_id + 1
      st.session_state["buf_students"].append(
          (new_id, f_name.strip(), f_surname.strip(), f_grade.strip())
      )
      st.session_state["has_unsaved_changes"] = True
      st.sidebar.success(
          f"Ученик {f_name} {f_surname} добавлен в буфер! (Не забудьте"
          " сохранить)"
      )
      st.rerun()
    else:
      st.sidebar.error("Все поля обязательны для заполнения!")

all_student_dict = {}
for sid, name, surname, grade in all_students:
  grade_str = f" ({grade})" if grade and grade != "-" else ""
  display_name = f"{surname} {name}{grade_str}"
  all_student_dict[display_name] = sid

# --- Легенда ---
st.sidebar.divider()
st.sidebar.markdown("""
### 📌 Легенда

**Посещение:**
* 🟢 — присутствовал
* 🟡 — отменил заранее
* 🔴 — несвоевременно отменил
* 🔘 — не заполнено

**Оплата:**
* 💰 — оплачено 
* ⛔ — не оплачено

**Домашнее задание:**
* 📘 — заполнено 
* 📕 — не заполнено
""")

# --- Экран: Фильтры ---
st.header("Электронный журнал")

today = date.today()
monday_of_current_week = today - timedelta(days=today.weekday())
sunday_of_current_week = monday_of_current_week + timedelta(days=6)

all_grade_nums = sorted(
    list(
        set(
            extract_grade_num(g) for _, _, _, g in all_students if g and g != "-"
        )
    )
)

f_col1, f_col2, f_col3 = st.columns(3)
with f_col1:
  start_date = st.date_input(
      "С какого числа", value=monday_of_current_week, key="start"
  )
with f_col2:
  end_date = st.date_input("По какое число", value=sunday_of_current_week, key="end")
with f_col3:
  filter_grade = st.selectbox(
      "Фильтр по классу (цифра)", ["Все классы"] + all_grade_nums
  )

st.divider()


def build_emoji_string(stat, paid, hw):
  if stat == "Присутствовал":
    p_emoji = "🟢"
  elif stat == "Отменил заранее":
    p_emoji = "🟡"
  elif stat == "Несвоевременно отменил":
    p_emoji = "🔴"
  else:
    p_emoji = "🔘"

  pay_emoji = "💰" if paid == 1 else "⛔"
  hw_emoji = "📘" if (hw and hw.strip()) else "📕"

  return f"{p_emoji} {pay_emoji} {hw_emoji}"


@st.dialog("🗑️ Подтверждение удаления")
def delete_student_dialog(student_id, student_fullname):
  st.warning(
      f"Вы действительно хотите удалить ученика **{student_fullname}** из буфера?"
  )
  col_yes, col_no = st.columns(2)
  with col_yes:
    if st.button("Да, удалить", type="primary", use_container_width=True):
      st.session_state["buf_students"] = [
          s for s in st.session_state["buf_students"] if s[0] != student_id
      ]
      st.session_state["buf_attendance"] = {
          k: v
          for k, v in st.session_state["buf_attendance"].items()
          if k[0] != student_id
      }
      st.session_state["has_unsaved_changes"] = True
      st.success("Ученик удален из буфера!")
      st.rerun()
  with col_no:
    if st.button("Отмена", use_container_width=True):
      st.rerun()


# --- Основной экран: Таблица посещаемости (по буферу) ---
if all_student_dict and start_date <= end_date:
  date_range = [
      (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
      for i in range((end_date - start_date).days + 1)
  ]

  table_data = {}
  for sid, name, surname, grade in all_students:
    g_num = extract_grade_num(grade)
    if (
        filter_grade != "Все классы"
        and g_num != filter_grade
        and grade != filter_grade
    ):
      continue

    full_name = f"{surname} {name}" + (
        f" [{grade}]" if grade and grade != "-" else ""
    )
    table_data[full_name] = {
        pd.to_datetime(d).strftime("%d.%m"): "" for d in date_range
    }

    for d_str in date_range:
      att_data = st.session_state["buf_attendance"].get((sid, d_str))
      if att_data and att_data["lesson_exists"] == 1:
        formatted_d = pd.to_datetime(d_str).strftime("%d.%m")
        if formatted_d in table_data[full_name]:
          table_data[full_name][formatted_d] = build_emoji_string(
              att_data["status"], att_data["paid"], att_data["homework"]
          )

  df = pd.DataFrame.from_dict(table_data, orient="index")
  if not df.empty:
    df = df.sort_index()

    st.markdown(
        "💡 *Таблица показывает данные из локального буфера. Изменения"
        " сохраняются кнопкой слева.*"
    )
    st.dataframe(df, use_container_width=True)

    # --- Карточка ученика ---
    st.divider()
    st.subheader("📋 Карточка ученика и управление занятием")

    table_student_options = ["-- Выберите ученика --"] + list(df.index)
    selected_student_row = st.selectbox(
        "Выберите ученика для просмотра карточки",
        table_student_options,
        key="card_student_select",
    )

    if selected_student_row != "-- Выберите ученика --":
      selected_sid = None
      for sid, name, surname, grade in all_students:
        fn = f"{surname} {name}" + (
            f" [{grade}]" if grade and grade != "-" else ""
        )
        if fn == selected_student_row:
          selected_sid = sid
          break

      if selected_sid:
        s_data = next(
            (s for s in all_students if s[0] == selected_sid), None
        )
        if s_data:
          _, s_name, s_surname, s_grade = s_data

          edit_mode_key = f"edit_mode_{selected_sid}"
          if edit_mode_key not in st.session_state:
            st.session_state[edit_mode_key] = False

          with st.container():
            if not st.session_state[edit_mode_key]:
              grade_display = (
                  f"Класс: {s_grade}"
                  if s_grade and s_grade != "-"
                  else "Без класса"
              )
              st.markdown(
                  f"**Ученик:** {s_surname} {s_name} &nbsp;|&nbsp;"
                  f" **{grade_display}**"
              )

              lesson_date = st.date_input(
                  "Дата урока для настройки",
                  value=date.today(),
                  key=f"card_date_{selected_sid}",
              )
              lesson_date_str = lesson_date.strftime("%Y-%m-%d")

              state_init_key = f"init_{selected_sid}_{lesson_date_str}"
              if state_init_key not in st.session_state:
                att_record = st.session_state["buf_attendance"].get(
                    (selected_sid, lesson_date_str), {}
                )
                st.session_state[f"les_exist_{selected_sid}"] = bool(
                    att_record.get("lesson_exists", 0)
                )
                st.session_state[f"status_sel_{selected_sid}"] = att_record.get(
                    "status", ""
                )
                st.session_state[f"paid_chk_{selected_sid}"] = bool(
                    att_record.get("paid", 0)
                )
                st.session_state[f"hw_txt_{selected_sid}"] = att_record.get(
                    "homework", ""
                )
                st.session_state[state_init_key] = True


              def update_buffer_data():
                l_exists = (
                    1
                    if st.session_state.get(f"les_exist_{selected_sid}")
                    else 0
                )
                stat = st.session_state.get(
                    f"status_sel_{selected_sid}", ""
                )
                paid = (
                    1 if st.session_state.get(f"paid_chk_{selected_sid}") else 0
                )
                hw = st.session_state.get(f"hw_txt_{selected_sid}", "")

                if (
                    l_exists == 0
                    and not stat
                    and paid == 0
                    and not hw.strip()
                ):
                  if (selected_sid, lesson_date_str) in st.session_state[
                      "buf_attendance"
                  ]:
                    del st.session_state["buf_attendance"][
                        (selected_sid, lesson_date_str)
                    ]
                else:
                  st.session_state["buf_attendance"][
                      (selected_sid, lesson_date_str)
                  ] = {
                      "status": stat,
                      "paid": paid,
                      "lesson_exists": l_exists,
                      "homework": hw,
                  }
                st.session_state["has_unsaved_changes"] = True


              lesson_exists_toggle = st.checkbox(
                  "Урок есть",
                  key=f"les_exist_{selected_sid}",
                  on_change=update_buffer_data,
              )

              if lesson_exists_toggle:
                st.markdown("---")
                status_options = [
                    "",
                    "Присутствовал",
                    "Отменил заранее",
                    "Несвоевременно отменил",
                ]
                current_st_val = st.session_state.get(
                    f"status_sel_{selected_sid}", ""
                )
                default_idx = (
                    status_options.index(current_st_val)
                    if current_st_val in status_options
                    else 0
                )

                st.selectbox(
                    "Посещаемость",
                    status_options,
                    index=default_idx,
                    key=f"status_sel_{selected_sid}",
                    on_change=update_buffer_data,
                )

                st.checkbox(
                    "Оплата получена",
                    key=f"paid_chk_{selected_sid}",
                    on_change=update_buffer_data,
                )

                st.text_area(
                    "Текущее домашнее задание",
                    key=f"hw_txt_{selected_sid}",
                    on_change=update_buffer_data,
                )
                st.markdown(
                    "💡 *Изменения записаны в буфер. Не забудьте нажать кнопку"
                    " «Сохранить в облако» слева.*"
                )

              st.divider()
              col_btn1, _, col_btn2 = st.columns([2, 3, 2])
              with col_btn1:
                if st.button(
                    "✏️ Изменить данные ученика", key=f"btn_edit_{selected_sid}"
                ):
                  st.session_state[edit_mode_key] = True
                  st.rerun()
              with col_btn2:
                if st.button(
                    "🗑️ Удалить ученика", key=f"btn_del_native_{selected_sid}"
                ):
                  delete_student_dialog(
                      selected_sid, f"{s_surname} {s_name}"
                  )

            else:
              with st.form(f"edit_form_{selected_sid}"):
                new_name = st.text_input("Имя", value=s_name)
                new_surname = st.text_input("Фамилия", value=s_surname)
                new_grade = st.text_input(
                    "Класс (или '-' если без класса)", value=s_grade
                )

                f_col1, f_col2 = st.columns(2)
                with f_col1:
                  save_btn = st.form_submit_button("💾 Сохранить карточку")
                with f_col2:
                  cancel_btn = st.form_submit_button("❌ Отмена")

                if save_btn:
                  if (
                      new_name.strip()
                      and new_surname.strip()
                      and new_grade.strip()
                  ):
                    st.session_state["buf_students"] = [
                        (
                            s[0],
                            (
                                new_name.strip()
                                if s[0] == selected_sid
                                else s[1]
                            ),
                            (
                                new_surname.strip()
                                if s[0] == selected_sid
                                else s[2]
                            ),
                            (
                                new_grade.strip()
                                if s[0] == selected_sid
                                else s[3]
                            ),
                        )
                        for s in st.session_state["buf_students"]
                    ]
                    st.session_state["has_unsaved_changes"] = True
                    st.session_state[edit_mode_key] = False
                    st.success("Данные ученика обновлены в буфере!")
                    st.rerun()
                  else:
                    st.error("Все поля должны быть заполнены.")

                if cancel_btn:
                  st.session_state[edit_mode_key] = False
                  st.rerun()
    else:
      st.info("💡 Выберите ученика в списке выше для работы с карточкой")

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
    exp_date_range = [
        (export_start + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range((export_end - export_start).days + 1)
    ]

    exp_table_data = {}
    for sid, name, surname, grade in all_students:
      full_name = f"{surname} {name}" + (
          f" [{grade}]" if grade and grade != "-" else ""
      )
      exp_table_data[full_name] = {
          pd.to_datetime(d).strftime("%d.%m"): "" for d in exp_date_range
      }

      for d_str in exp_date_range:
        att_data = st.session_state["buf_attendance"].get((sid, d_str))
        if att_data and att_data["lesson_exists"] == 1:
          formatted_d = pd.to_datetime(d_str).strftime("%d.%m")
          if formatted_d in exp_table_data[full_name]:
            exp_table_data[full_name][formatted_d] = build_emoji_string(
                att_data["status"], att_data["paid"], att_data["homework"]
            )

    exp_df = pd.DataFrame.from_dict(exp_table_data, orient="index")
    if not exp_df.empty:
      exp_df = exp_df.sort_index()
      exp_df = exp_df.reset_index()
      exp_df.rename(columns={"index": "Ученик"}, inplace=True)

      import io

      output = io.BytesIO()
      with pd.ExcelWriter(output, engine="openpyxl") as writer:
        exp_df.to_excel(writer, index=False, sheet_name="Посещаемость")

      excel_data = output.getvalue()

      st.sidebar.download_button(
          label="💾 Скачать файл",
          data=excel_data,
          file_name=f"tutor_report_{export_start.strftime('%d.%m.%Y')}-{export_end.strftime('%d.%m.%Y')}.xlsx",
          mime=(
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          ),
      )
    else:
      st.sidebar.warning("Нет данных за выбранный период.")