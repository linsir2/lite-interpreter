"""Streamlit entrypoint for lite-interpreter demo pages."""
from __future__ import annotations

from src.frontend.pages.knowledge_manager import render_knowledge_manager
from src.frontend.pages.skill_manager import render_skill_manager
from src.frontend.pages.task_console import render_task_console


def main() -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    page = st.sidebar.selectbox(
        "Page",
        options=["Task Console", "Knowledge Manager", "Skill Manager"],
        index=0,
    )
    if page == "Knowledge Manager":
        render_knowledge_manager()
        return
    if page == "Skill Manager":
        render_skill_manager()
        return
    render_task_console()


if __name__ == "__main__":
    main()
