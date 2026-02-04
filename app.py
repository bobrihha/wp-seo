"""
AI Content Hub - Demo Entry Point
Handles authentication, then delegates to main.py with demo_code in session_state.
"""

import streamlit as st
from utils.demo_codes import DemoCodeManager


def render_login():
    """Render the demo code login page."""
    st.set_page_config(page_title="AI Content Hub - Demo", page_icon="📰", layout="centered")
    
    st.markdown("""
    <style>
        .main-title {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: center;
        }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<p class="main-title">📰 AI Content Hub</p>', unsafe_allow_html=True)
    st.caption("Автоматическая генерация контента из RSS, YouTube, Telegram")
    
    st.success("🔑 **Для получения пробного доступа пишите:** [@CACHALOT_ai](https://t.me/CACHALOT_ai)")
    
    st.divider()
    st.markdown("### 🔐 Вход в демо-режим")
    
    with st.form("demo_login"):
        code = st.text_input("Демо-код", placeholder="DEMO-XXXXXX", max_chars=20)
        submitted = st.form_submit_button("Войти", type="primary", use_container_width=True)
        
        if submitted and code:
            manager = DemoCodeManager()
            is_valid, message = manager.validate_code(code)
            if is_valid:
                st.session_state.demo_code = code.upper().strip()
                st.session_state.is_authenticated = True
                st.rerun()
            else:
                st.error(f"❌ {message}")
    
    st.divider()
    with st.expander("🔧 Панель администратора"):
        admin_pw = st.text_input("Пароль", type="password", key="admin_pw")
        if st.button("Войти как админ"):
            if admin_pw == "admin2024":
                st.session_state.is_admin = True
                st.session_state.is_authenticated = True
                st.rerun()
            else:
                st.error("Неверный пароль")
    
    st.divider()
    st.markdown("📞 **Контакт:** [@CACHALOT_ai](https://t.me/CACHALOT_ai)")


def render_admin():
    """Render admin panel for demo code management."""
    st.set_page_config(page_title="Content Hub Admin", page_icon="📰", layout="wide")
    
    manager = DemoCodeManager()
    stats = manager.get_stats()
    
    with st.sidebar:
        st.markdown("## 🔧 Admin")
        st.metric("Всего кодов", stats["total_codes"])
        st.metric("Статей", stats["total_articles_generated"])
        
        st.divider()
        if st.button("🚪 Выйти"):
            st.session_state.is_admin = False
            st.session_state.is_authenticated = False
            st.rerun()
        
        st.markdown("[@CACHALOT_ai](https://t.me/CACHALOT_ai)")
    
    st.markdown("## 🔧 Управление демо-кодами")
    
    tab1, tab2 = st.tabs(["📋 Все коды", "➕ Создать"])
    
    with tab1:
        codes = manager.get_all_codes()
        for code in sorted(codes, key=lambda c: c.created_at, reverse=True):
            emoji = "🟢" if code.active and not code.is_exhausted else "🔴"
            with st.expander(f"{emoji} {code.code}"):
                st.write(f"Статей: {code.articles_used}/{code.articles_limit}, Изобр: {code.images_used}/{code.images_limit}")
                c1, c2 = st.columns(2)
                if c1.button("Сбросить", key=f"r_{code.code}"):
                    manager.reset_code(code.code)
                    st.rerun()
                if c2.button("Удалить", key=f"d_{code.code}"):
                    manager.delete_code(code.code)
                    st.rerun()
    
    with tab2:
        with st.form("create"):
            count = st.number_input("Количество", value=20)
            arts = st.number_input("Статей", value=10)
            imgs = st.number_input("Изображений", value=10)
            if st.form_submit_button("Создать"):
                codes = manager.generate_batch(count=count, articles_limit=arts, images_limit=imgs)
                st.text_area("Коды:", "\n".join([c.code for c in codes]), height=300)


def main():
    """Main entry point with authentication."""
    if "is_authenticated" not in st.session_state:
        st.session_state.is_authenticated = False
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False
    if "demo_code" not in st.session_state:
        st.session_state.demo_code = None
    
    if not st.session_state.is_authenticated:
        render_login()
        return
    
    if st.session_state.is_admin:
        render_admin()
        return
    
    # Demo user - run main.py (which checks is_demo_mode() and hides API keys)
    from main import main as original_main
    original_main()


if __name__ == "__main__":
    main()
