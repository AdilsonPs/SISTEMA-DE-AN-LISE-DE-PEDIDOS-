import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import base64

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
                        all_data.append({'Cod Sap': material, 'Descrição': denom, 'Qtd': vals[0], 'VLR UND PED': vals[1], 'Total': vals[2]})
    return pd.DataFrame(all_data)

# --- INTERFACE ---
st.title("🏢 SISTEMA DE ANÁLISE DE PEDIDOS (APS)")

with st.sidebar:
    st.header("⚙️ Configurações")
    modalidade = st.radio("Modalidade do Pedido:", ["CIF (PDF)", "FOB (Excel)"])
    
    st.header("📁 Upload")
    file_excel_precos = st.file_uploader("Tabela de Preços (Excel)", type=['xlsx'])
    
    file_pedido = None
    if modalidade == "CIF (PDF)":
        file_pedido = st.file_uploader("Pedido do Cliente (PDF)", type=['pdf'])
    else:
        file_pedido = st.file_uploader("Arquivo de Conferência (Excel/FOB)", type=['xlsx'])

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
            
            df_ped = pd.DataFrame({
                'Cod Sap': df_fob_raw['Material'].astype(str).str.strip(),
                'Descrição': df_fob_raw['Descrição do Material'],
                'Qtd': pd.to_numeric(df_fob_raw['Quant. Ped.Período'], errors='coerce'),
                'VLR UND PED': pd.to_numeric(df_fob_raw['Valor FD / CX'], errors='coerce'),
                'VLR DESC FOB': pd.to_numeric(df_fob_raw['Desc.Vendedor'], errors='coerce').fillna(0)
            })
            df_ped['Total'] = df_ped['Qtd'] * df_ped['VLR UND PED']
            df_ped = df_ped.dropna(subset=['Cod Sap', 'VLR UND PED'])
            df_ped = df_ped[df_ped['Cod Sap'] != 'nan']

        if not df_ped.empty:
            df = pd.merge(df_ped, df_precos[['Cod Sap', 'Tab_Price', 'Categoria']], on='Cod Sap', how='left')
            df['Tab_Price'] = df['Tab_Price'].fillna(0)
            
            df['Desc Unit R$'] = df['Tab_Price'] - df['VLR UND PED']
            df['Desc Total R$'] = df['Desc Unit R$'] * df['Qtd']
            df['Desc %'] = df.apply(lambda x: (x['Desc Unit R$'] / x['Tab_Price'] * 100) if x['Tab_Price'] > 0 else 0, axis=1)
            
            # --- CÁLCULOS DE RESUMO ---
            total_ped = df['Total'].sum()
            total_desc_tab = df['Desc Total R$'].sum()
            total_tabela = (df['Tab_Price'] * df['Qtd']).sum()
            margem_final = ((total_ped - total_tabela) / total_ped * 100) if total_ped > 0 else 0
            
            st.write(f"### 📈 Resumo Geral ({modalidade.split(' ')[0]})")
            
            # Primeira Linha de Métricas
            r1_c1, r1_c2, r1_c3 = st.columns(3)
            r1_c1.metric("Itens no Pedido", len(df))
            r1_c2.metric("Preço Total Tabela", fmt_br(total_tabela))
            r1_c3.metric("Total Líquido Pedido", fmt_br(total_ped))

            # Segunda Linha de Métricas (Onde entra o VLR DESC FOB)
            r2_c1, r2_c2, r2_c3 = st.columns(3)
            r2_c1.metric("Desc. vs Tabela (Total)", fmt_br(total_desc_tab))
            
            if modalidade == "FOB (Excel)":
                # Cálculo do Desconto FOB Total (Somatório de Desc.Vendedor por item * Qtd)
                total_desc_vendedor = (df['VLR DESC FOB'] * df['Qtd']).sum()
                r2_c2.metric("VLR DESC FOB (Vendedor)", fmt_br(total_desc_vendedor))
            else:
                perc_desc_global = (total_desc_tab / total_tabela * 100) if total_tabela > 0 else 0
                r2_c2.metric("% Desconto Global", f"{perc_desc_global:.2f}%")
            
            r2_c3.metric("Margem Final", f"{margem_final:.2f}%")

            st.markdown("---")
            
            # --- TABELA DETALHADA ---
            st.write("### 📊 Detalhamento dos Itens")
            df_view = df.copy()
            cols_to_fmt = ['VLR UND PED', 'Total', 'Tab_Price', 'Desc Unit R$', 'Desc Total R$']
            if 'VLR DESC FOB' in df_view.columns: cols_to_fmt.append('VLR DESC FOB')
            
            for col in cols_to_fmt:
                df_view[col] = df_view[col].apply(fmt_br)
            
            df_view['Desc %'] = df_view['Desc %'].map('{:.2f}%'.format)
            
            show_cols = ['Cod Sap', 'Categoria', 'Descrição', 'Qtd', 'Tab_Price', 'VLR UND PED']
            if modalidade == "FOB (Excel)": show_cols.append('VLR DESC FOB')
            show_cols += ['Desc %', 'Total']
            
            st.dataframe(df_view[show_cols], use_container_width=True)

            # Download
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            st.sidebar.markdown("---")
            st.sidebar.download_button("📥 Baixar Excel", output.getvalue(), "analise_aps.xlsx", use_container_width=True)
    
    except Exception as e:
        st.error(f"Erro: {e}")
