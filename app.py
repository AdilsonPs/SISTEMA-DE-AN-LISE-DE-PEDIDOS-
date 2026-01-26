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
        # 1. Carregar Tabela de Preços
        df_precos = pd.read_excel(file_excel_precos, dtype={'Cod Sap': str})
        df_precos['Cod Sap'] = df_precos['Cod Sap'].astype(str).str.strip()
        df_precos['Tab_Price'] = pd.to_numeric(df_precos['Price'], errors='coerce')
        if 'Categoria' not in df_precos.columns:
            df_precos['Categoria'] = 'Geral'

        df_ped = pd.DataFrame()

        # 2. Lógica de Extração
        if modalidade == "CIF (PDF)":
            df_ped = extract_pdf_data(file_pedido)
            if not df_ped.empty:
                for c in ['VLR UND PED', 'Total', 'Qtd']:
                    df_ped[c] = df_ped[c].astype(str).str.replace('.', '').str.replace(',', '.').astype(float)
        else:
            # Lógica FOB corrigida para a aba Resumo
            # Lemos a aba 'Resumo' pulando as 2 linhas de cabeçalho (Data do documento...)
            df_fob_raw = pd.read_excel(file_pedido, sheet_name='Resumo', skiprows=2)
            
            # Limpeza de nomes de colunas (remove espaços extras que o Excel costuma colocar)
            df_fob_raw.columns = df_fob_raw.columns.str.strip()
            
            # Mapeamento conforme sua instrução
            df_ped = pd.DataFrame()
            df_ped['Cod Sap'] = df_fob_raw['Material'].astype(str).str.strip()
            df_ped['Descrição'] = df_fob_raw['Descrição do Material']
            df_ped['Qtd'] = pd.to_numeric(df_fob_raw['Quant. Ped.Período'], errors='coerce')
            df_ped['VLR UND PED'] = pd.to_numeric(df_fob_raw['Valor FD / CX'], errors='coerce')
            
            # Se o valor total não existir ou estiver errado, fazemos a conta manual
            if 'Valor Total' in df_fob_raw.columns:
                df_ped['Total'] = pd.to_numeric(df_fob_raw['Valor Total'], errors='coerce')
            else:
                df_ped['Total'] = df_ped['Qtd'] * df_ped['VLR UND PED']
            
            # Remove linhas vazias ou totais de rodapé da planilha
            df_ped = df_ped.dropna(subset=['Cod Sap', 'VLR UND PED'])
            df_ped = df_ped[df_ped['Cod Sap'] != 'nan']

        # 3. Cruzamento e Cálculos
        if not df_ped.empty:
            df = pd.merge(df_ped, df_precos[['Cod Sap', 'Tab_Price', 'Categoria']], on='Cod Sap', how='left')
            
            # Preenche preços de tabela não encontrados com 0 para evitar erro no cálculo
            df['Tab_Price'] = df['Tab_Price'].fillna(0)
            
            # Cálculos solicitados
            df['Desc Unit R$'] = df['Tab_Price'] - df['VLR UND PED']
            df['Desc Total R$'] = df['Desc Unit R$'] * df['Qtd']
            
            # Cálculo de % com proteção contra divisão por zero
            df['Desc %'] = df.apply(lambda x: (x['Desc Unit R$'] / x['Tab_Price'] * 100) if x['Tab_Price'] > 0 else 0, axis=1)
            df['Margem %'] = df.apply(lambda x: ((x['VLR UND PED'] - x['Tab_Price']) / x['VLR UND PED'] * 100) if x['VLR UND PED'] > 0 else 0, axis=1)

            # --- EXIBIÇÃO ---
            st.write(f"### 📈 Resumo Geral - Modalidade {modalidade.split(' ')[0]}")
            
            total_ped = df['Total'].sum()
            total_desc = df['Desc Total R$'].sum()
            total_tabela = df.apply(lambda x: x['Tab_Price'] * x['Qtd'], axis=1).sum()
            
            perc_desconto_global = (total_desc / total_tabela * 100) if total_tabela > 0 else 0
            margem_final = ((total_ped - total_tabela) / total_ped * 100) if total_ped > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Itens no Pedido", len(df))
            col2.metric("Preço Total Tabela", fmt_br(total_tabela))
            col3.metric("Total Líquido Pedido", fmt_br(total_ped))

            col4, col5, col6 = st.columns(3)
            col4.metric("Desconto Total (R$)", fmt_br(total_desc))
            col5.metric("% Desconto Global", f"{perc_desconto_global:.2f}%", delta_color="inverse")
            col6.metric("Margem Final (Ponderada)", f"{margem_final:.2f}%")

            st.markdown("---")
            
            # Detalhes e Categorias (mesma lógica anterior)
            st.write("### 📂 Análise por Categoria")
            cat_group = df.groupby('Categoria').agg({'Total': 'sum', 'Desc %': 'mean'}).reset_index()
            cols_cat = st.columns(len(cat_group) if len(cat_group) > 0 else 1)
            for i, row in cat_group.iterrows():
                with cols_cat[i]:
                    st.metric(label=row['Categoria'], value=fmt_br(row['Total']), 
                              delta=f"Desc. Médio: {row['Desc %']:.2f}%", delta_color="inverse")

            st.write("### 📊 Detalhamento dos Itens")
            df_view = df.copy()
            for col in ['VLR UND PED', 'Total', 'Tab_Price', 'Desc Unit R$', 'Desc Total R$']:
                df_view[col] = df_view[col].apply(fmt_br)
            
            df_view['Desc %'] = df_view['Desc %'].map('{:.2f}%'.format)
            df_view['Margem %'] = df_view['Margem %'].map('{:.2f}%'.format)

            cols_grid = ['Cod Sap', 'Categoria', 'Descrição', 'Qtd', 'Tab_Price', 'VLR UND PED', 'Desc %', 'Margem %', 'Total']
            st.dataframe(df_view[cols_grid], use_container_width=True)

            # Botão de Download na Sidebar
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            st.sidebar.markdown("---")
            st.sidebar.download_button("📥 Baixar Análise em Excel", output.getvalue(), "analise_aps.xlsx", use_container_width=True)

        else:
            st.warning("Não foi possível encontrar dados válidos no arquivo de pedido.")

    except Exception as e:
        st.error(f"Ocorreu um erro ao processar os arquivos: {e}")
        st.info("Dica: Verifique se a aba do arquivo FOB chama-se exatamente 'Resumo'.")
