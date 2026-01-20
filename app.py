import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Sistema APS", layout="wide")

# --- ESTILO CSS AJUSTADO (Para leitura em Dark/Light Mode) ---
st.markdown("""
    <style>
    /* Estilização dos Cards para ficarem visíveis */
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; color: #1a73e8 !important; }
    [data-testid="stMetricLabel"] { font-weight: bold !important; text-transform: uppercase !important; }
    .stMetric {
        background-color: #ffffff !important;
        padding: 15px !important;
        border-radius: 10px !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important;
        border: 1px solid #e0e0e0 !important;
    }
    /* Ajuste para que o texto dentro do card branco seja sempre escuro */
    [data-testid="stMetricLabel"] > div { color: #5f6368 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- FUNÇÕES DE APOIO ---
def fmt_br(v):
    return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') if pd.notnull(v) else "R$ 0,00"

def extract_pdf_data(file):
    all_data = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                t = round(w['top'], 0)
                lines.setdefault(t, []).append(w)
            for t in sorted(lines.keys()):
                txt = " ".join([w['text'] for w in lines[t]])
                match = re.search(r'^(\d{5,}-\d)', txt)
                if match:
                    material = match.group(1)
                    denom = ""
                    for t_next in sorted(lines.keys()):
                        if t < t_next < t + 15:
                            denom = " ".join([w['text'] for w in lines[t_next]])
                            break
                    vals = re.findall(r'\d+[\d.]*,\d+', txt)
                    if len(vals) >= 3:
                        all_data.append({'Cod Sap': material, 'Descrição': denom, 'Qtd': vals[0], 'Unit': vals[1], 'Total': vals[2]})
    return pd.DataFrame(all_data)

# --- INTERFACE ---
st.title("🏢 SISTEMA DE ANÁLISE DE PEDIDOS (APS)")

with st.sidebar:
    st.header("📁 Upload")
    file_excel = st.file_uploader("Tabela de Preços (Excel)", type=['xlsx'])
    file_pdf = st.file_uploader("Pedido do Cliente (PDF)", type=['pdf'])

if file_excel and file_pdf:
    try:
        df_precos = pd.read_excel(file_excel, dtype={'Cod Sap': str})
        df_precos['Cod Sap'] = df_precos['Cod Sap'].astype(str).str.strip()
        df_precos['Tab_Price'] = pd.to_numeric(df_precos['Price'], errors='coerce')

        df_ped = extract_pdf_data(file_pdf)
        
        if not df_ped.empty:
            for c in ['Unit', 'Total', 'Qtd']:
                df_ped[c] = df_ped[c].astype(str).str.replace('.', '').str.replace(',', '.').astype(float)

            df = pd.merge(df_ped, df_precos[['Cod Sap', 'Tab_Price']], on='Cod Sap', how='left')
            
            # Cálculos Corrigidos
            df['Desc Unit R$'] = df['Tab_Price'] - df['Unit']
            df['Desc Total R$'] = df['Desc Unit R$'] * df['Qtd']
            df['Desc %'] = (df['Desc Unit R$'] / df['Tab_Price']) * 100
            df['Margem %'] = ((df['Unit'] - df['Tab_Price']) / df['Unit']) * 100

            # Dashboard
            total_ped = df['Total'].sum()
            total_desc = df['Desc Total R$'].sum()
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Itens", f"{len(df)}")
            c2.metric("Desconto Total", fmt_br(total_desc), delta=f"-{total_desc/total_ped*100:.1f}%", delta_color="inverse")
            c3.metric("Total Pedido", fmt_br(total_ped))
            c4.metric("Preço Tabela", fmt_br(total_ped + total_desc))

            st.write("### 📊 Detalhamento dos Itens")
            
            # FORMATAÇÃO DA TABELA (Colunas Financeiras)
            df_view = df.copy()
            cols_financeiras = ['Unit', 'Total', 'Tab_Price', 'Desc Unit R$', 'Desc Total R$']
            for col in cols_financeiras:
                df_view[col] = df_view[col].apply(fmt_br)
            
            df_view['Desc %'] = df_view['Desc %'].map('{:.2f}%'.format)
            df_view['Margem %'] = df_view['Margem %'].map('{:.2f}%'.format)

            st.dataframe(df_view, use_container_width=True)

            # Botão de Download
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 Baixar Excel", output.getvalue(), "analise.xlsx")

    except Exception as e:
        st.error(f"Erro: {e}")
      
