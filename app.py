import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Sistema APS - Análise de Pedidos", layout="wide")

# --- ESTILO CSS PERSONALIZADO ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #eee; }
    .css-1r6slb0 { border-radius: 10px; }
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
st.subheader("Transforme pedidos em PDF em análises de margem instantâneas")

with st.sidebar:
    st.header("📁 Upload de Arquivos")
    file_excel = st.file_uploader("Tabela de Preços (Excel)", type=['xlsx'])
    file_pdf = st.file_uploader("Pedido do Cliente (PDF)", type=['pdf'])
    
    st.info("O sistema cruzará o código SAP para calcular descontos e margens.")

if file_excel and file_pdf:
    try:
        # Processamento Excel
        df_precos = pd.read_excel(file_excel, dtype={'Cod Sap': str})
        df_precos['Cod Sap'] = df_precos['Cod Sap'].astype(str).str.strip()
        df_precos['Tab_Price'] = pd.to_numeric(df_precos['Price'], errors='coerce')

        # Processamento PDF
        df_ped = extract_pdf_data(file_pdf)
        
        if not df_ped.empty:
            for c in ['Unit', 'Total', 'Qtd']:
                df_ped[c] = df_ped[c].astype(str).str.replace('.', '').str.replace(',', '.').astype(float)

            # Cálculos
            df = pd.merge(df_ped, df_precos[['Cod Sap', 'Tab_Price']], on='Cod Sap', how='left')
            df['Desc Unit R$'] = df['Tab_Price'] - df['Unit']
            df['Desc Total R$'] = df['Desc Unit R$'] * df['Qtd']
            df['Desc %'] = (df['Desc Unit R$'] / df['Tab_Price']) * 100
            df['Margem %'] = ((df['Unit'] - df['Tab_Price']) / df['Unit']) * 100

            # --- DASHBOARD ---
            total_ped = df['Total'].sum()
            total_desc = df['Desc Total R$'].sum()
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Itens", len(df))
            c2.metric("Desconto Total", fmt_br(total_desc), delta=f"-{total_desc/total_ped*100:.1f}%", delta_color="inverse")
            c3.metric("Total Pedido", fmt_br(total_ped))
            c4.metric("Preço Tabela Total", fmt_br(total_ped + total_desc))

            # --- TABELA ---
            st.write("### 📊 Detalhamento dos Itens")
            
            # Formatação para exibição
            df_display = df.copy()
            df_display['Tab_Price'] = df_display['Tab_Price'].apply(fmt_br)
            df_display['Unit'] = df_display['Unit'].apply(fmt_br)
            df_display['Total'] = df_display['Total'].apply(fmt_br)
            df_display['Desc %'] = df_display['Desc %'].map('{:.2f}%'.format)
            df_display['Margem %'] = df_display['Margem %'].map('{:.2f}%'.format)

            st.dataframe(df_display, use_container_width=True)

            # Download
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise')
            
            st.download_button(
                label="📥 Baixar Análise em Excel",
                data=output.getvalue(),
                file_name="analise_pedido.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.error("Não foi possível extrair dados do PDF. Verifique o formato.")

    except Exception as e:
        st.error(f"Erro ao processar: {e}")
else:
    st.warning("Aguardando upload dos arquivos para iniciar a análise...")
