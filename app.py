import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import base64

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Sistema APS", layout="wide")

# Função para converter imagem local para base64
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

# Fundo com imagem
try:
    bin_str = get_base64_of_bin_file('logo.jpg') 
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
except:
    st.warning("Imagem de fundo 'logo.jpg' não encontrada.")

# --- ESTILO CSS ---
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
                        all_data.append({'Cod Sap': material, 'Descrição': denom, 'Qtd': vals[0], 'VLR UND PED': vals[1], 'Total': vals[2]})
    return pd.DataFrame(all_data)

# --- INTERFACE ---
st.title("🏢 SISTEMA DE ANÁLISE DE PEDIDOS (APS)")

with st.sidebar:
    st.header("📁 Upload")
    file_excel = st.file_uploader("Tabela de Preços (Excel)", type=['xlsx'])
    file_pdf = st.file_uploader("Pedido do Cliente (PDF)", type=['pdf'])

if file_excel and file_pdf:
    try:
        # Lendo Excel - Agora trazendo a coluna Categoria
        df_precos = pd.read_excel(file_excel, dtype={'Cod Sap': str})
        df_precos['Cod Sap'] = df_precos['Cod Sap'].astype(str).str.strip()
        df_precos['Tab_Price'] = pd.to_numeric(df_precos['Price'], errors='coerce')
        
        # Garante que a coluna Categoria existe, se não cria uma padrão
        if 'Categoria' not in df_precos.columns:
            df_precos['Categoria'] = 'Geral'

        df_ped = extract_pdf_data(file_pdf)
        
        if not df_ped.empty:
            for c in ['VLR UND PED', 'Total', 'Qtd']:
                df_ped[c] = df_ped[c].astype(str).str.replace('.', '').str.replace(',', '.').astype(float)

            # Merge trazendo Categoria
            df = pd.merge(df_ped, df_precos[['Cod Sap', 'Tab_Price', 'Categoria']], on='Cod Sap', how='left')
            
            # Cálculos
            df['Desc Unit R$'] = df['Tab_Price'] - df['VLR UND PED']
            df['Desc Total R$'] = df['Desc Unit R$'] * df['Qtd']
            df['Desc %'] = (df['Desc Unit R$'] / df['Tab_Price']) * 100
            df['Margem %'] = ((df['VLR UND PED'] - df['Tab_Price']) / df['VLR UND PED']) * 100

            # --- DASHBOARD PRINCIPAL ---
            total_ped = df['Total'].sum()
            total_desc = df['Desc Total R$'].sum()
            
            st.write("### 📈 Resumo Geral")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Itens", f"{len(df)}")
            c2.metric("Desconto Total", fmt_br(total_desc))
            c3.metric("Total Pedido", fmt_br(total_ped))
            c4.metric("Preço Tabela", fmt_br(total_ped + total_desc))

            # --- DASHBOARD POR CATEGORIA ---
            st.write("### 📂 Análise por Categoria")
            
            # Agrupando dados por categoria
            cat_group = df.groupby('Categoria').agg({
                'Total': 'sum',
                'Desc %': 'mean',
                'Desc Total R$': 'sum'
            }).reset_index()

            # Criando colunas dinâmicas para cada categoria (máximo 4 por linha)
            cols_cat = st.columns(len(cat_group))
            for i, row in cat_group.iterrows():
                with cols_cat[i]:
                    label = f"{row['Categoria']}"
                    valor_ped = fmt_br(row['Total'])
                    desc_medio = f"{row['Desc %']:.2f}%"
                    st.metric(label, valor_ped, delta=f"Desconto Médio: {desc_medio}", delta_color="inverse")

            # --- TABELA DETALHADA ---
            st.write("### 📊 Detalhamento dos Itens")
            df_view = df.copy()
            for col in ['VLR UND PED', 'Total', 'Tab_Price', 'Desc Unit R$', 'Desc Total R$']:
                df_view[col] = df_view[col].apply(fmt_br)
            
            df_view['Desc %'] = df_view['Desc %'].map('{:.2f}%'.format)
            df_view['Margem %'] = df_view['Margem %'].map('{:.2f}%'.format)

            cols = ['Cod Sap', 'Categoria', 'Descrição', 'Qtd', 'Tab_Price', 'VLR UND PED', 'Desc %', 'Total']
            st.dataframe(df_view[cols], use_container_width=True)

            # Download
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 Baixar Excel Completo", output.getvalue(), "analise_aps_categorias.xlsx")

    except Exception as e:
        st.error(f"Erro no processamento: {e}")
