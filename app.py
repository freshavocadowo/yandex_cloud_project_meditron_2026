"""Streamlit review UI; only anonymized document content is displayed/exported."""
import io
import json
from pathlib import Path
import zipfile

import streamlit as st

from statchem.pipeline import process
from statchem.settings import Settings

st.set_page_config(page_title="StatChem · Эпикриз → JSON", page_icon="🩺", layout="wide")
st.title("Эпикриз → 50 признаков")
st.caption("Синтетические документы медицинского хакатона · Проверяемые цитаты · 9 групп")
st.info("Прототип для исследовательской демонстрации. Используйте только синтетические эпикризы.")
mode = st.sidebar.selectbox("Способ извлечения", ["rules", "yandex"], format_func=lambda x: "Локальные правила" if x == "rules" else "Правила + YandexGPT")
use_ner = st.sidebar.checkbox("Локальное распознавание имён (Natasha)", value=True, disabled=mode == "yandex")
files = sorted(Path("participant-kit-realistic-v2-100/documents").glob("*.md"))
selected = st.sidebar.selectbox("Документ из корпуса", files, format_func=lambda p: p.stem) if files else None
upload = st.sidebar.file_uploader("Или загрузите синтетический .md", type=["md"])
if st.sidebar.button("Извлечь признаки", type="primary"):
    try:
        text = upload.getvalue().decode("utf-8-sig") if upload else selected.read_text(encoding="utf-8-sig")
        settings = Settings()
        settings.use_ner = True if mode == "yandex" else use_ner
        with st.spinner("Обезличивание, извлечение и проверка цитат…"):
            result = process(text, settings, mode)
        st.session_state["processed"] = result
        st.session_state["document_id"] = selected.stem if not upload else "synthetic-document"
    except Exception as exc:
        st.session_state.pop("processed", None)
        st.error(f"Обработка остановлена ({type(exc).__name__}). Проверьте конфигурацию и синтетический документ.")
if "processed" in st.session_state:
    result = st.session_state["processed"]
    report = result.report
    cols = st.columns(3)
    cols[0].metric("Поля", "50 / 50")
    cols[1].metric("Подтверждены цитатой", sum(e["verified"] for e in report["evidence"].values()))
    cols[2].metric("Предупреждения", len(report["warnings"]))
    if report["warnings"]:
        st.warning("Требуется проверка: " + "; ".join(report["warnings"]))
    left, right = st.columns([1, 1.3])
    with left:
        st.subheader("Обезличенный эпикриз")
        st.text_area("Текст с сохранёнными координатами", result.masked_text, height=620, disabled=True)
    with right:
        tab_fields, tab_json = st.tabs(["Значения и цитаты", "JSON"])
        with tab_fields:
            for group, values in result.output.items():
                with st.expander(group):
                    for field, value in values.items():
                        ev = report["evidence"][field]
                        st.markdown(f"**{field}**")
                        st.text(value)
                        if ev["quote"]:
                            st.code(ev["quote"], language=None)
                            st.caption(f"{ev['section']} · символы {ev['start']}–{ev['end']} · {ev['source']}")
                        else:
                            st.caption("Значение по правилу пропуска; подтверждающей цитаты нет.")
        with tab_json:
            st.json(result.output)
    st.download_button("Скачать JSON", json.dumps(result.output, ensure_ascii=False, indent=2), st.session_state["document_id"] + ".json", "application/json")
    with st.expander("Лабораторные измерения: выбранные и повторные"):
        st.dataframe(report["laboratory_observations"], hide_index=True, use_container_width=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("result.json", json.dumps(result.output, ensure_ascii=False, indent=2))
        archive.writestr("evidence.json", json.dumps(report, ensure_ascii=False, indent=2))
        archive.writestr("anonymized.md", result.masked_text)
    st.download_button("Скачать JSON, цитаты и текст", buffer.getvalue(), "statchem-review.zip", "application/zip")
