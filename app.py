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

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; color: #0d47a1 !important; }
    [data-testid="stMetricLabel"] { font-weight: bold !important; color: #333333 !important; }
    .stMetric {
        background-color: rgba(255, 255, 255, 0.95) !important;
        padding: 15px !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 10px rgba(0,0,0,0.1) !important;
        border: 1px solid #ddd !important;
    }
    </style>
    """, unsafe_allow_html=True)

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
                        all_data.append({
                            'Cod Sap': material, 
                            'Descrição': denom, 
                            'Qtd': vals[0], 
                            'VLR UND PED': vals[1], 
                            'Total': vals[2]
                        })
    return pd.DataFrame(all_data)

# --- INTERFACE SIDEBAR ---
st.title("🏢 SISTEMA DE ANÁLISE DE PEDIDOS (APS)")

with st.sidebar:
    st.header("👤 Identificação")
    cliente_input = st.text_input("Nome do Cliente:", "")
    cliente_nome = cliente_input.upper()
    
    st.header("⚙️ Configurações")
    modalidade = st.radio("Modalidade do Pedido:", ["CIF (PDF)", "FOB (Excel)"])
    
    st.header("📁 Upload")
    file_excel_precos = st.file_uploader("Tabela de Preços (Excel)", type=['xlsx'])
    
    file_pedido = None
    if modalidade == "CIF (PDF)":
        file_pedido = st.file_uploader("Pedido do Cliente (PDF)", type=['pdf'])
    else:
        file_pedido = st.file_uploader("Arquivo de Conferência (Excel/FOB)", type=['xlsx'])

    st.header("📲 Enviar Resumo")
    wpp_destinatario = st.text_input("Nome do Destinatário", "Gestor")
    wpp_numero = st.text_input("Número (com DDD)", "55011999999999")

if file_excel_precos and file_pedido:
    try:
        df_precos = pd.read_excel(file_excel_precos, dtype={'Cod Sap': str})
        df_precos['Cod Sap'] = df_precos['Cod Sap'].astype(str).str.strip()
        df_precos['Tab_Price'] = pd.to_numeric(df_precos['Price'], errors='coerce')
        if 'Categoria' not in df_precos.columns:
            df_precos['Categoria'] = 'Geral'

        df_ped = pd.DataFrame()

        if modalidade == "CIF (PDF)":
            df_ped = extract_pdf_data(file_pedido)
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
            if 'Desc.Vendedor' in df_fob_raw.columns:
                df_ped['%FOB'] = pd.to_numeric(df_fob_raw['Desc.Vendedor'], errors='coerce')
            if 'Valor Total' in df_fob_raw.columns:
                df_ped['Total'] = pd.to_numeric(df_fob_raw['Valor Total'], errors='coerce')
            else:
                df_ped['Total'] = df_ped['Qtd'] * df_ped['VLR UND PED']
            df_ped = df_ped.dropna(subset=['Cod Sap', 'VLR UND PED'])
            df_ped = df_ped[df_ped['Cod Sap'] != 'nan']

        if not df_ped.empty:
            df = pd.merge(df_ped, df_precos[['Cod Sap', 'Tab_Price', 'Categoria']], on='Cod Sap', how='left')
            df['Tab_Price'] = df['Tab_Price'].fillna(0)
            
            # Cálculos de Desconto e Margem por Item
            df['Desc Unit R$'] = df['Tab_Price'] - df['VLR UND PED']
            df['Desc %'] = df.apply(lambda x: (x['Desc Unit R$'] / x['Tab_Price'] * 100) if x['Tab_Price'] > 0 else 0, axis=1)
            # Margem calculada sobre o Valor do Pedido (Venda)
            df['Margem %'] = df.apply(lambda x: ((x['VLR UND PED'] - x['Tab_Price']) / x['VLR UND PED'] * 100) if x['VLR UND PED'] > 0 else 0, axis=1)

            # --- PROCESSAMENTO DOS TOTAIS ---
            total_ped = df['Total'].sum()
            total_tabela = df.apply(lambda x: x['Tab_Price'] * x['Qtd'], axis=1).sum()
            perc_desconto_global = ( (total_tabela - total_ped) / total_tabela * 100) if total_tabela > 0 else 0
            margem_final = ((total_ped - total_tabela) / total_ped * 100) if total_ped > 0 else 0
            
            # --- MONTAGEM DA MENSAGEM WHATSAPP ---
            mod_clean = modalidade.split(' ')[0]
            msg = f"📦 *Resumo de Pedido - {cliente_nome} - {mod_clean}*\n\n"
            msg += f"📋 *Itens:* {len(df)}\n"
            msg += f"💰 *Total Líquido:* {fmt_br(total_ped)}\n"
            msg += f"📉 *% Desc Total:* {perc_desconto_global:.2f}%\n"
            msg += f"📈 *% Margem Projetada:* {margem_final:.2f}%\n\n"
            
            msg += "📂 *Resumo por Categoria:*\n"
            cat_group = df.groupby('Categoria').agg({'Total': 'sum', 'Desc %': 'mean'}).reset_index()
            for _, row in cat_group.iterrows():
                msg += f"▪️ {row['Categoria']}: {fmt_br(row['Total'])} (Desc: {row['Desc %']:.2f}%)\n"
            
            msg += "\n_Gerado automaticamente pelo Sistema APS_"
            whatsapp_link = f"https://wa.me/{wpp_numero}?text={urllib.parse.quote(msg)}"

            # --- EXIBIÇÃO NA TELA ---
            st.write(f"### 📈 Análise: {cliente_nome} ({mod_clean})")
            
            # Linha 1: Métricas de Volume/Valor
            m1, m2, m3 = st.columns(3)
            m1.metric("Itens no Pedido", len(df))
            m2.metric("Preço Total Tabela", fmt_br(total_tabela))
            m3.metric("Total Líquido Pedido", fmt_br(total_ped))

            # Linha 2: Métricas de Rentabilidade
            if mod_clean == "FOB" and '%FOB' in df.columns:
                media_fob = df['%FOB'].mean()
                if 0 < media_fob < 1: media_fob *= 100
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Desconto Total (R$)", fmt_br(total_tabela - total_ped))
                c2.metric("% Desc Total", f"{perc_desconto_global:.2f}%", delta_color="inverse")
                c3.metric("% Margem Projetada", f"{margem_final:.2f}%")
                c4.metric("Média %FOB", f"{media_fob:.2f}%")
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Desconto Total (R$)", fmt_br(total_tabela - total_ped))
                c2.metric("% Desc Total", f"{perc_desconto_global:.2f}%", delta_color="inverse")
                c3.metric("% Margem Projetada", f"{margem_final:.2f}%")

            # Botão WhatsApp na Sidebar
            st.sidebar.markdown(f'''
                <a href="{whatsapp_link}" target="_blank">
                    <button style="width:100%; background-color:#25D366; color:white; border:none; padding:10px; border-radius:5px; cursor:pointer; font-weight:bold;">
                        🚀 Enviar Resumo via WhatsApp
                    </button>
                </a>
                ''', unsafe_allow_html=True)

            st.markdown("---")
            st.write("### 📂 Detalhes por Categoria")
            cols_cat = st.columns(len(cat_group))
            for i, row in cat_group.iterrows():
                with cols_cat[i]:
                    st.metric(label=row['Categoria'], value=fmt_br(row['Total']), delta=f"Desc: {row['Desc %']:.2f}%", delta_color="inverse")

            st.markdown("---")
            st.write("### 📊 Detalhes dos Itens")
            df_view = df.copy()
            
            # Organização das colunas na tabela
            cols_grid = ['Cod Sap', 'Categoria', 'Descrição', 'Qtd', 'Tab_Price', 'VLR UND PED', 'Desc %', 'Margem %', 'Total']
            if '%FOB' in df_view.columns: cols_grid.insert(6, '%FOB')

            # Formatação de Moeda para exibição
            for col in ['VLR UND PED', 'Total', 'Tab_Price']:
                df_view[col] = df_view[col].apply(fmt_br)
            
            # Formatação de Percentual para exibição
            df_view['Desc %'] = df_view['Desc %'].apply(lambda x: f"{x:.2f}%")
            df_view['Margem %'] = df_view['Margem %'].apply(lambda x: f"{x:.2f}%")
            if '%FOB' in df_view.columns:
                df_view['%FOB'] = df_view['%FOB'].apply(lambda x: f"{x:.2f}%")

            st.dataframe(df_view[cols_grid], use_container_width=True)

        else:
            st.warning("Não foi possível encontrar dados válidos no arquivo.")
    except Exception as e:
        st.error(f"Erro ao processar: {e}")
