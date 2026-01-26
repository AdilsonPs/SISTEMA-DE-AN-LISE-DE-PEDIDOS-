import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import base64
import urllib.parse

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Sistema APS", layout="wide")

def get_base64_of_bin_file(bin_file):
    try:
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    except:
        return None

bin_str = get_base64_of_bin_file('logo.jpg') 
if bin_str:
    bg_img_code = f"""
    <style>
    .stApp {{
        background-image: linear-gradient(rgba(255,255,255,0.85), rgba(255,255,255,0.85)), url("data:image/png;base64,{bin_str}");
        background-size: cover;
        background-attachment: fixed;
    }}
    </style>
    """
    st.markdown(bg_img_code, unsafe_allow_html=True)

def fmt_br(v):
    return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') if pd.notnull(v) else "R$ 0,00"

def extract_pdf_data(file):
    all_data = []
    cliente = "Não identificado"
    with pdfplumber.open(file) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += page.extract_text() + "\n"
            words = page.extract_words()
            lines = {}
            for w in words:
                t = round(w['top'], 0)
                lines.setdefault(t, []).append(w)
            
            for t in sorted(lines.keys()):
                txt = " ".join([w['text'] for w in lines[t]])
                
                # Tenta capturar o nome do cliente (ajuste o padrão conforme seu PDF)
                if "Nome:" in txt or "Razão Social:" in txt:
                    cliente = txt.split(":")[-1].strip()

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
                        all_data.append({
                            'Cod Sap': material, 'Descrição': denom, 'Qtd': vals[0], 
                            'VLR UND PED': vals[1], 'Total': vals[2]
                        })
    return pd.DataFrame(all_data), cliente

# --- INTERFACE SIDEBAR ---
st.title("🏢 SISTEMA DE ANÁLISE DE PEDIDOS (APS)")

with st.sidebar:
    st.header("⚙️ Configurações")
    modalidade = st.radio("Modalidade do Pedido:", ["CIF (PDF)", "FOB (Excel)"])
    file_excel_precos = st.file_uploader("Tabela de Preços (Excel)", type=['xlsx'])
    
    if modalidade == "CIF (PDF)":
        file_pedido = st.file_uploader("Pedido do Cliente (PDF)", type=['pdf'])
    else:
        file_pedido = st.file_uploader("Arquivo de Conferência (Excel/FOB)", type=['xlsx'])

    st.header("📲 Enviar Resumo")
    wpp_numero = st.text_input("WhatsApp (DDD + Número)", "5511999999999")

if file_excel_precos and file_pedido:
    try:
        df_precos = pd.read_excel(file_excel_precos, dtype={'Cod Sap': str})
        df_precos['Cod Sap'] = df_precos['Cod Sap'].astype(str).str.strip()
        df_precos['Tab_Price'] = pd.to_numeric(df_precos['Price'], errors='coerce')
        if 'Categoria' not in df_precos.columns: df_precos['Categoria'] = 'Geral'

        df_ped = pd.DataFrame()
        cliente_final = "Cliente Excel"

        if modalidade == "CIF (PDF)":
            df_ped, cliente_final = extract_pdf_data(file_pedido)
            if not df_ped.empty:
                for c in ['VLR UND PED', 'Total', 'Qtd']:
                    df_ped[c] = df_ped[c].astype(str).str.replace('.', '').str.replace(',', '.').astype(float)
        else:
            df_fob_raw = pd.read_excel(file_pedido, sheet_name='Resumo', skiprows=2)
            df_fob_raw.columns = df_fob_raw.columns.str.strip()
            df_ped = pd.DataFrame()
            df_ped['Cod Sap'] = df_fob_raw['Material'].astype(str).str.strip()
            df_ped['Descrição'] = df_fob_raw['Descrição do Material']
            df_ped['Qtd'] = pd.to_numeric(df_fob_raw['Quant. Ped.Período'], errors='coerce')
            df_ped['VLR UND PED'] = pd.to_numeric(df_fob_raw['Valor FD / CX'], errors='coerce')
            if 'Desc.Vendedor' in df_fob_raw.columns: df_ped['%FOB'] = pd.to_numeric(df_fob_raw['Desc.Vendedor'], errors='coerce')
            df_ped['Total'] = df_ped['Qtd'] * df_ped['VLR UND PED']
            df_ped = df_ped.dropna(subset=['Cod Sap', 'VLR UND PED'])

        if not df_ped.empty:
            df = pd.merge(df_ped, df_precos[['Cod Sap', 'Tab_Price', 'Categoria']], on='Cod Sap', how='left')
            df['Tab_Price'] = df['Tab_Price'].fillna(0)
            df['Desc %'] = df.apply(lambda x: ((x['Tab_Price'] - x['VLR UND PED']) / x['Tab_Price'] * 100) if x['Tab_Price'] > 0 else 0, axis=1)
            
            total_ped = df['Total'].sum()
            cat_summary = df.groupby('Categoria')['Total'].sum()

            # --- MENSAGEM WHATSAPP ---
            msg = f"🟢 *Resumo de Pedido APS*\n\n"
            msg += f"🏢 *Cliente:* {cliente_final}\n"
            msg += f"💰 *Total Líquido:* {fmt_br(total_ped)}\n\n"
            msg += f"📂 *Resumo por Categoria:*\n"
            for cat, val in cat_summary.items():
                msg += f"• {cat}: {fmt_br(val)}\n"
            
            if modalidade == "FOB (Excel)" and '%FOB' in df.columns:
                m_fob = df['%FOB'].mean()
                if 0 < m_fob < 1: m_fob *= 100
                msg += f"\n🚛 *Média %FOB:* {m_fob:.2f}%"

            msg += "\n\n_Gerado pelo Sistema APS_"
            whatsapp_link = f"https://wa.me/{wpp_numero}?text={urllib.parse.quote(msg)}"

            # --- EXIBIÇÃO ---
            st.write(f"### 📈 Pedido: {cliente_final}")
            
            # Métricas principais
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("Total Líquido", fmt_br(total_ped))
            col_m2.metric("Itens", len(df))
            
            if modalidade == "FOB (Excel)" and '%FOB' in df.columns:
                col_m3.metric("Média %FOB", f"{m_fob:.2f}%")

            st.sidebar.markdown(f'<a href="{whatsapp_link}" target="_blank"><button style="width:100%; background-color:#25D366; color:white; border:none; padding:10px; border-radius:5px; font-weight:bold;">🚀 Enviar WhatsApp</button></a>', unsafe_allow_html=True)

            st.markdown("---")
            st.write("### 📂 Categorias")
            cols_c = st.columns(len(cat_summary))
            for i, (cat, val) in enumerate(cat_summary.items()):
                cols_c[i].metric(cat, fmt_br(val))

            st.markdown("---")
            st.write("### 📊 Detalhes dos Itens")
            df_view = df.copy()
            
            # Formatação de Porcentagem para o Grid
            df_view['Desc %'] = df_view['Desc %'].apply(lambda x: f"{x:.2f}%")
            if '%FOB' in df_view.columns:
                df_view['%FOB'] = df_view['%FOB'].apply(lambda x: f"{x*100:.2f}%" if x < 1 and x > 0 else f"{x:.2f}%" if pd.notnull(x) else "0.00%")

            grid_cols = ['Cod Sap', 'Categoria', 'Descrição', 'Qtd', 'Tab_Price', 'VLR UND PED', 'Desc %', 'Total']
            if '%FOB' in df_view.columns: grid_cols.insert(7, '%FOB')
            
            st.dataframe(df_view[grid_cols], use_container_width=True)

    except Exception as e:
        st.error(f"Erro: {e}")
